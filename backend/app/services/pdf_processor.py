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

_VLM_PROMPT = (
    "以上图片为竖排繁体中文古籍，图中的大号加粗字体为古籍正文，"
    "小号字体为注文，我需要将正文和注文作隔断区分。"
    "请为我OCR该图片，区分正文与注文，并严格以如下JSON格式输出：\n"
    '{"正文": "此处放正文内容", "注文": "此处放注文内容"}\n'
    "要求：1.仅输出JSON，不要输出任何其他内容。"
    "2.若该页无注文，则注文字段输出空字符串。"
    "3.若该页无正文，则正文字段输出空字符串。"
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


def _parse_vlm_response(text: str) -> tuple[str, str]:
    """Extract 正文 (body) and 注文 (annotation) from VLM JSON response.

    Returns (body_text, annotation_text). Either may be empty.
    """
    # Strip markdown code fences if present (e.g. ```json ... ```)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
        body = str(data.get("正文", "")).strip()
        annotation = str(data.get("注文", "")).strip()
        return body, annotation
    except (json.JSONDecodeError, AttributeError):
        logger.warning("VLM response is not valid JSON, falling back to raw text")

    # Fallback: treat whole response as body
    return text.strip(), ""


def _ocr_page_vlm(img_bytes: bytes, model: str, api_key: str) -> tuple[str, str]:
    """Send a page image to DashScope VLM and return (body, annotation).

    Uses the OpenAI-compatible SDK.
    """
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


def extract_text_from_pdf(
    filepath: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[tuple[int, str, str]]:
    """
    Extract text from every page of a PDF file.

    1. Fast pre-scan (single-threaded): extract text-layer pages and
       identify image-only pages needing OCR.
    2. Parallel VLM OCR via ThreadPoolExecutor for image-only pages.

    Returns a list of (page_number, body_text, annotation_text) tuples
    (1-indexed pages).  For text-layer pages, annotation_text is empty.
    """
    text_pages: list[tuple[int, str, str]] = []
    ocr_page_indices: list[int] = []

    try:
        with fitz.open(filepath) as doc:
            total_pages = doc.page_count

            # Pre-scan: extract text pages & identify OCR pages
            for i, page in enumerate(doc):
                text = page.get_text().strip()
                if text:
                    text_pages.append((i + 1, text, ""))
                else:
                    ocr_page_indices.append(i)

    except fitz.FileDataError:
        logger.error("PDF file is corrupted or encrypted: %s", filepath)
        raise ValueError(f"Cannot read PDF: {filepath}")
    except Exception:
        logger.exception("Unexpected error processing PDF: %s", filepath)
        raise

    text_count = len(text_pages)

    # Report text pages as already done
    if progress_callback:
        progress_callback(text_count, total_pages)

    # Parallel VLM OCR for image-only pages
    if ocr_page_indices:
        api_key = _get_api_key()
        if not api_key:
            logger.warning(
                "No DashScope API key configured; skipping OCR for %d scanned pages",
                len(ocr_page_indices),
            )
            text_pages.sort(key=lambda x: x[0])
            return text_pages

        model = _get_ocr_model()

        # Render all OCR pages to PNG bytes first
        page_images: dict[int, bytes] = {}
        with fitz.open(filepath) as doc:
            for idx in ocr_page_indices:
                page = doc[idx]
                pix = page.get_pixmap(dpi=300)
                page_images[idx] = pix.tobytes("png")

        num_workers = min(8, len(ocr_page_indices))
        logger.info(
            "Parallel VLM OCR: %d pages, %d threads, model=%s",
            len(ocr_page_indices), num_workers, model,
        )

        completed = 0

        def _ocr_one(page_idx: int) -> tuple[int, str, str]:
            img_bytes = page_images[page_idx]
            body, annotation = _ocr_page_vlm(img_bytes, model, api_key)
            return (page_idx + 1, body, annotation)

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            future_to_idx = {
                pool.submit(_ocr_one, idx): idx
                for idx in ocr_page_indices
            }
            for future in as_completed(future_to_idx):
                page_idx = future_to_idx[future]
                try:
                    page_num, body, annotation = future.result()
                    if body or annotation:
                        text_pages.append((page_num, body, annotation))
                except Exception:
                    logger.warning(
                        "VLM OCR failed for page %d", page_idx + 1,
                        exc_info=True,
                    )

                completed += 1
                if progress_callback:
                    progress_callback(text_count + completed, total_pages)

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
    """
    Process a PDF in a background thread.

    Extracts text page-by-page (with parallel VLM OCR for scanned pages),
    indexes into FTS5 in batches (body and annotation separately),
    and updates the file status when done.
    Progress is broadcast via WebSocket to all connected clients.
    """
    if progress_callback is None:
        progress_callback = _make_ws_progress_callback(file_id)

    def _worker() -> None:
        try:
            pages = extract_text_from_pdf(filepath, progress_callback)
            total = len(pages)
            batch: list[tuple[int, int, str, str]] = []
            for page_num, body, annotation in pages:
                if body:
                    batch.append((file_id, page_num, body, "body"))
                if annotation:
                    batch.append((file_id, page_num, annotation, "annotation"))
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
