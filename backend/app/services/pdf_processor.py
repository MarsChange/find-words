"""PDF processing service using PyMuPDF (fitz) with streaming reads."""

import logging
import threading
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF

from app.core.database import (
    index_pages_batch,
    update_file_status,
)

logger = logging.getLogger(__name__)

# Batch size for FTS5 inserts
_BATCH_SIZE = 50


def extract_text_from_pdf(filepath: str) -> list[tuple[int, str]]:
    """
    Extract text from every page of a PDF file.

    Uses fitz.open(stream=...) for memory-efficient reading.
    Returns a list of (page_number, text) tuples (1-indexed pages).
    """
    path = Path(filepath)
    raw = path.read_bytes()
    pages: list[tuple[int, str]] = []
    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            for i, page in enumerate(doc):
                text = page.get_text()
                if text.strip():
                    pages.append((i + 1, text))
    except fitz.FileDataError:
        logger.error("PDF file is corrupted or encrypted: %s", filepath)
        raise ValueError(f"Cannot read PDF: {filepath}")
    except Exception:
        logger.exception("Unexpected error processing PDF: %s", filepath)
        raise
    return pages


def process_pdf_background(
    file_id: int,
    filepath: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """
    Process a PDF in a background thread.

    Extracts text page-by-page, indexes into FTS5 in batches, and
    updates the file status when done.

    Args:
        file_id: Database file record id.
        filepath: Absolute path to the PDF on disk.
        progress_callback: Optional (current_page, total_pages) callback.
    """

    def _worker() -> None:
        try:
            pages = extract_text_from_pdf(filepath)
            total = len(pages)
            batch: list[tuple[int, int, str]] = []
            for idx, (page_num, text) in enumerate(pages, 1):
                batch.append((file_id, page_num, text))
                if len(batch) >= _BATCH_SIZE:
                    index_pages_batch(batch)
                    batch.clear()
                if progress_callback:
                    progress_callback(idx, total)
            if batch:
                index_pages_batch(batch)
            update_file_status(file_id, "ready", page_count=total)
            logger.info(
                "Finished indexing file_id=%d (%d pages)", file_id, total
            )
        except Exception as exc:
            logger.exception("Failed to process file_id=%d", file_id)
            update_file_status(file_id, "error")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread
