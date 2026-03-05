"""PDF processing service using PyMuPDF (fitz) with parallel RapidOCR."""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF

from app.core.database import (
    index_pages_batch,
    update_file_status,
)
from app.core.ws_manager import broadcast_sync

logger = logging.getLogger(__name__)

# Batch size for FTS5 inserts
_DB_BATCH_SIZE = 50

# Number of parallel OCR workers (auto-detect based on CPU cores)
_OCR_WORKERS = min(os.cpu_count() or 4, 10)

# Lazy-loaded RapidOCR instance (heavy to initialize)
_ocr_engine = None
_ocr_lock = threading.Lock()


def _get_ocr():
    """Get or create the RapidOCR engine (thread-safe singleton)."""
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    with _ocr_lock:
        if _ocr_engine is not None:
            return _ocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
            logger.info("RapidOCR engine initialized")
            return _ocr_engine
        except ImportError:
            logger.warning(
                "rapidocr_onnxruntime not installed. "
                "Scanned PDFs will not be indexed. "
                "Install with: pip install rapidocr_onnxruntime"
            )
            return None


def _render_and_ocr(raw: bytes, page_idx: int) -> tuple[int, str]:
    """Render a single page and run OCR. Thread-safe (opens own document)."""
    with fitz.open(stream=raw, filetype="pdf") as doc:
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")

    # OCR outside the fitz context to free page/pixmap memory early
    ocr = _get_ocr()
    if ocr is None:
        return (page_idx + 1, "")
    try:
        result, _ = ocr(img_bytes)
        if not result:
            return (page_idx + 1, "")
        lines = [text for _, text, score in result if score > 0.5]
        return (page_idx + 1, "\n".join(lines))
    except Exception:
        logger.debug("OCR failed for page %d", page_idx + 1, exc_info=True)
        return (page_idx + 1, "")


def extract_text_from_pdf(
    filepath: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[tuple[int, str]]:
    """
    Extract text from every page of a PDF file.

    1. Fast pre-scan (single-threaded): extract text-layer pages and
       identify image-only pages needing OCR.
    2. Fully parallel render+OCR: each worker opens its own document,
       renders its assigned page, and runs OCR — all in parallel.

    Returns a list of (page_number, text) tuples (1-indexed pages).
    """
    path = Path(filepath)
    raw = path.read_bytes()

    text_pages: list[tuple[int, str]] = []
    ocr_page_indices: list[int] = []

    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            total_pages = doc.page_count

            # ── Pre-scan: extract text pages & identify OCR pages ──
            for i, page in enumerate(doc):
                text = page.get_text().strip()
                if text:
                    text_pages.append((i + 1, text))
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

    # ── Parallel render + OCR (each worker opens its own doc) ──────────
    if ocr_page_indices and _get_ocr() is not None:
        logger.info(
            "Parallel render+OCR: %d pages, %d workers",
            len(ocr_page_indices), _OCR_WORKERS,
        )

        completed = 0
        with ThreadPoolExecutor(max_workers=_OCR_WORKERS) as pool:
            future_to_page = {
                pool.submit(_render_and_ocr, raw, idx): idx
                for idx in ocr_page_indices
            }
            for future in as_completed(future_to_page):
                try:
                    page_num, text = future.result()
                    if text:
                        text_pages.append((page_num, text))
                except Exception:
                    page_idx = future_to_page[future]
                    logger.debug("Render+OCR failed for page %d", page_idx + 1, exc_info=True)

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

    Extracts text page-by-page (with parallel OCR for scanned pages),
    indexes into FTS5 in batches, and updates the file status when done.
    Progress is broadcast via WebSocket to all connected clients.
    """
    if progress_callback is None:
        progress_callback = _make_ws_progress_callback(file_id)

    def _worker() -> None:
        try:
            pages = extract_text_from_pdf(filepath, progress_callback)
            total = len(pages)
            batch: list[tuple[int, int, str]] = []
            for page_num, text in pages:
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
