"""PDF processing service using PyMuPDF (fitz) with DashScope VLM OCR."""

import base64
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import fitz  # PyMuPDF

from app.core.database import (
    get_setting,
    index_pages_batch,
    update_file_status,
)
from app.core.ws_manager import broadcast_sync

logger = logging.getLogger(__name__)

# Batch size for FTS5 inserts
_DB_BATCH_SIZE = 50

# DashScope VLM configuration
_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_OCR_MAX_ATTEMPTS_WHEN_EMPTY_TEXT = 2

_VLM_PROMPT = (
"""
你是“古籍OCR转写助手”。

任务：
请对输入的竖排繁体中文古籍页面进行高精度OCR转写。

要求：
1. 页面阅读顺序为：自右向左逐列，每列自上而下。
2. 必须输出页面中全部可辨认文字与符号，不得遗漏：
   - 大字正文
   - 小字注文/夹注/边注
   - 标点、引号、圈点、书名号等符号
   - 页码、版心、题头等可辨认文字
3. 只做转写，不做解释，不做改写，不做现代化替换。
4. 保留繁体字形与原文用字。

输出格式：
- 严格只输出 JSON，不要输出任何解释或 markdown。
- JSON 格式固定为：{"text":"此处放整页按阅读顺序拼接的转写文本"}
- 若无法识别到文字，则输出：{"text":""}
"""
)


def _get_api_key() -> str | None:
    """Return the DashScope API key.

    Priority: DASHSCOPE_API_KEY env var > configured llm_provider_api_key.
    """
    key = os.environ.get("DASHSCOPE_API_KEY")
    if key:
        return key
    import app.config as cfg
    return cfg.settings.llm_provider_api_key or None


def _get_ocr_model() -> str:
    """Read the OCR model name from DB settings."""
    model = get_setting("ocr_model")
    return model or "qwen3.5-plus"


def _parse_vlm_response(text: str) -> str:
    """Extract OCR full-page text from VLM JSON response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
        return str(data.get("text", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        logger.warning("VLM response is not valid JSON, falling back to raw text")
        return text.strip()


def _ocr_page_vlm(img_bytes: bytes, model: str, api_key: str) -> str:
    """Send a page image to DashScope VLM and return full-page text."""
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=_DASHSCOPE_BASE_URL,
    )

    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    completion = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": _VLM_PROMPT},
            ],
        }],
        response_format={"type": "json_object"},
    )
    response_text = completion.choices[0].message.content or ""
    return _parse_vlm_response(response_text)


def _ocr_page_with_retry(
    img_bytes: bytes,
    model: str,
    api_key: str,
    page_num: int,
) -> str:
    """OCR with retry when text is empty."""
    last_text = ""

    for attempt in range(1, _OCR_MAX_ATTEMPTS_WHEN_EMPTY_TEXT + 1):
        text = _ocr_page_vlm(img_bytes, model, api_key)
        last_text = text

        if text.strip():
            if attempt > 1:
                logger.info(
                    "Page %d OCR text recovered on attempt %d/%d",
                    page_num,
                    attempt,
                    _OCR_MAX_ATTEMPTS_WHEN_EMPTY_TEXT,
                )
            return text

        if attempt < _OCR_MAX_ATTEMPTS_WHEN_EMPTY_TEXT:
            logger.warning(
                "Page %d OCR text is empty on attempt %d/%d, retrying...",
                page_num,
                attempt,
                _OCR_MAX_ATTEMPTS_WHEN_EMPTY_TEXT,
            )

    logger.warning(
        "Page %d OCR text is still empty after %d attempts",
        page_num,
        _OCR_MAX_ATTEMPTS_WHEN_EMPTY_TEXT,
    )
    return last_text


def extract_text_from_pdf(
    filepath: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[tuple[int, str]]:
    """Extract full-page OCR text from every page using VLM."""
    try:
        with fitz.open(filepath) as doc:
            total_pages = doc.page_count
    except fitz.FileDataError:
        logger.error("PDF file is corrupted or encrypted: %s", filepath)
        raise ValueError(f"Cannot read PDF: {filepath}")
    except Exception:
        logger.exception("Unexpected error processing PDF: %s", filepath)
        raise

    if progress_callback:
        progress_callback(0, total_pages)

    api_key = _get_api_key()
    if not api_key:
        logger.warning(
            "No DashScope API key configured; skipping VLM OCR for all %d pages",
            total_pages,
        )
        return []

    model = _get_ocr_model()

    page_images: dict[int, bytes] = {}
    with fitz.open(filepath) as doc:
        for i in range(total_pages):
            page = doc[i]
            pix = page.get_pixmap(dpi=400)
            page_images[i] = pix.tobytes("png")

    num_workers = min(8, total_pages)
    logger.info(
        "Parallel VLM OCR: %d pages, %d threads, model=%s",
        total_pages, num_workers, model,
    )

    text_pages: list[tuple[int, str]] = []
    completed = 0

    def _ocr_one(page_idx: int) -> tuple[int, str]:
        img_bytes = page_images[page_idx]
        text = _ocr_page_with_retry(
            img_bytes=img_bytes,
            model=model,
            api_key=api_key,
            page_num=page_idx + 1,
        )
        return page_idx + 1, text

    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        future_to_idx = {
            pool.submit(_ocr_one, idx): idx
            for idx in range(total_pages)
        }
        for future in as_completed(future_to_idx):
            page_idx = future_to_idx[future]
            try:
                page_num, text = future.result()
                if text:
                    text_pages.append((page_num, text))
            except Exception:
                logger.warning(
                    "VLM OCR failed for page %d", page_idx + 1,
                    exc_info=True,
                )

            completed += 1
            if progress_callback:
                progress_callback(completed, total_pages)

    text_pages.sort(key=lambda x: x[0])
    return text_pages


def _make_ws_progress_callback(file_id: int) -> Callable[[int, int], None]:
    """Create a progress callback that broadcasts via WebSocket."""
    def _callback(current: int, total: int) -> None:
        broadcast_sync({
            "type": "index_progress",
            "file_id": file_id,
            "current": current,
            "total": total,
        })
    return _callback


def process_pdf_background(
    file_id: int,
    filepath: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> threading.Thread:
    """Process a PDF in a background thread and index page text."""
    if progress_callback is None:
        progress_callback = _make_ws_progress_callback(file_id)

    def _worker() -> None:
        try:
            pages = extract_text_from_pdf(filepath, progress_callback)
            total = len(pages)
            batch: list[tuple[int, int, str]] = []
            for page_num, text in pages:
                if text:
                    batch.append((file_id, page_num, text))
                if len(batch) >= _DB_BATCH_SIZE:
                    index_pages_batch(batch)
                    batch.clear()
            if batch:
                index_pages_batch(batch)
            update_file_status(file_id, "ready", page_count=total)
            broadcast_sync({
                "type": "index_progress",
                "file_id": file_id,
                "status": "ready",
                "current": total,
                "total": total,
            })
            logger.info(
                "Finished indexing file_id=%d (%d pages with text)", file_id, total
            )
        except Exception:
            logger.exception("Failed to process file_id=%d", file_id)
            update_file_status(file_id, "error")
            broadcast_sync({
                "type": "index_progress",
                "file_id": file_id,
                "status": "error",
            })

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread
