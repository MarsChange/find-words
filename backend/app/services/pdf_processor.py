"""PDF processing service using PyMuPDF (fitz) with PaddleOCR."""

import logging
import os
import platform
import time
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable
import sys

# Disable OneDNN BEFORE importing paddle/paddleocr.
# PaddlePaddle 3.x auto-enables OneDNN on x86 Windows, causing
# fused_conv2d crashes. Must set both old and new flag names.
if platform.system() == "Windows":
    os.environ.setdefault('FLAGS_use_mkldnn', '0')
    os.environ.setdefault('FLAGS_use_onednn', '0')

import fitz  # PyMuPDF

from app.core.database import (
    index_pages_batch,
    update_file_status,
)
from app.core.ws_manager import broadcast_sync

logger = logging.getLogger(__name__)

# Batch size for FTS5 inserts
_DB_BATCH_SIZE = 50

# Windows uses sequential OCR (OneDNN crashes in spawned sub-processes).
# macOS/Linux use ProcessPoolExecutor for parallel OCR.
_IS_WINDOWS = platform.system() == "Windows"


def _patch_paddle_inference():
    """Monkey-patch paddle.inference.create_predictor to force-disable OneDNN.

    On Windows x86, PaddlePaddle's IR optimization passes (conv_bn_fuse_pass,
    conv_eltwiseadd_bn_fuse_pass) create fused_conv2d operators that invoke
    OneDNN internally, even when enable_mkldnn=False. This patch intercepts
    the config before predictor creation to explicitly disable OneDNN and
    remove problematic fuse passes.
    """
    try:
        from paddle import inference
    except ImportError:
        return

    _original = inference.create_predictor

    def _safe_create_predictor(config):
        # Force-disable OneDNN/MKLDNN at inference config level
        if hasattr(config, 'disable_mkldnn'):
            config.disable_mkldnn()
        if hasattr(config, 'disable_onednn'):
            config.disable_onednn()
        # Delete IR passes that produce fused_conv2d (requires OneDNN)
        for pass_name in [
            'conv_bn_fuse_pass',
            'conv_eltwiseadd_bn_fuse_pass',
            'conv_transpose_bn_fuse_pass',
            'conv_transpose_eltwiseadd_bn_fuse_pass',
            'conv_elementwise_add_mkldnn_fuse_pass',
            'depthwise_conv_mkldnn_pass',
        ]:
            try:
                config.delete_pass(pass_name)
            except Exception:
                pass
        return _original(config)

    inference.create_predictor = _safe_create_predictor
    logger.info("Patched paddle.inference.create_predictor to disable OneDNN")


# Apply the patch on Windows before any PaddleOCR model loading
if _IS_WINDOWS:
    _patch_paddle_inference()


def _diagnose_paddle_env():
    """Print diagnostic info about the PaddlePaddle / PaddleOCR environment.

    Run this on Windows to debug OneDNN issues.
    Call via:  python -c "from app.services.pdf_processor import _diagnose_paddle_env; _diagnose_paddle_env()"
    """
    print("=" * 60)
    print("PaddlePaddle / PaddleOCR Diagnostic Report")
    print("=" * 60)
    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"Python:   {sys.version}")

    # 1. Env vars
    print("\n--- OneDNN Environment Variables ---")
    for key in ['FLAGS_use_mkldnn', 'FLAGS_use_onednn', 'FLAGS_use_mkl']:
        print(f"  {key} = {os.environ.get(key, '<not set>')}")

    # 2. Paddle version and flags
    try:
        import paddle
        print(f"\n--- PaddlePaddle {paddle.__version__} ---")
        for flag in ['FLAGS_use_mkldnn', 'FLAGS_use_onednn']:
            try:
                val = paddle.get_flags([flag])
                print(f"  {flag} = {val[flag]}")
            except Exception as e:
                print(f"  {flag} = ERROR: {e}")
    except ImportError:
        print("\n  PaddlePaddle not installed!")
        return

    # 3. PaddleOCR version
    try:
        import paddleocr
        print(f"\n--- PaddleOCR {paddleocr.__version__} ---")
    except ImportError:
        print("\n  PaddleOCR not installed!")
        return

    # 4. Inference Config defaults
    print("\n--- Inference Config Defaults ---")
    from paddle import inference
    c = inference.Config()
    print(f"  mkldnn_enabled: {c.mkldnn_enabled()}")
    if hasattr(c, 'onednn_enabled'):
        print(f"  onednn_enabled: {c.onednn_enabled()}")

    # Check available passes
    if hasattr(c, 'pass_builder'):
        pb = c.pass_builder()
        if hasattr(pb, 'all_passes'):
            passes = pb.all_passes()
            fuse = [p for p in passes if 'fuse' in p or 'mkldnn' in p or 'onednn' in p]
            print(f"  Total IR passes: {len(passes)}")
            print(f"  Fuse/MKLDNN passes ({len(fuse)}):")
            for p in fuse:
                print(f"    {p}")

    # 5. Try creating PaddleOCR
    print("\n--- PaddleOCR Creation Test ---")
    from paddleocr import PaddleOCR
    try:
        ocr = PaddleOCR(
            use_angle_cls=True, lang="chinese_cht",
            show_log=False, enable_mkldnn=False,
        )
        print("  PaddleOCR created OK")
    except Exception as e:
        print(f"  PaddleOCR creation FAILED: {e}")
        return

    # 6. Try OCR on a tiny test image
    print("\n--- OCR Test (tiny image) ---")
    import numpy as np
    # Create a small white image with some black pixels
    img = np.ones((100, 300, 3), dtype=np.uint8) * 255
    try:
        result = ocr.ocr(img)
        print(f"  OCR on blank image: OK (result={result})")
    except Exception as e:
        print(f"  OCR on blank image FAILED: {type(e).__name__}: {e}")

    # 7. Try OCR on an actual PDF page if available
    print("\n--- OCR Test (PDF page) ---")
    import glob
    pdfs = glob.glob("data/uploads/*.pdf")
    if not pdfs:
        print("  No PDFs found in data/uploads/")
    else:
        pdf_path = pdfs[0]
        print(f"  Testing with: {pdf_path}")
        try:
            doc = fitz.open(pdf_path)
            # Find first image-only page
            test_page = None
            for i in range(min(10, doc.page_count)):
                if not doc[i].get_text().strip():
                    test_page = i
                    break
            if test_page is None:
                test_page = 0
            page = doc[test_page]
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            doc.close()
            print(f"  Page {test_page + 1}: {len(img_bytes)} bytes")
            t0 = time.time()
            result = ocr.ocr(img_bytes)
            t1 = time.time()
            if result and result[0]:
                lines = [line[1][0] for line in result[0]]
                print(f"  OCR OK: {len(lines)} lines, {t1-t0:.2f}s")
                print(f"  First line: {lines[0][:50]}")
            else:
                print(f"  OCR returned empty result, {t1-t0:.2f}s")
        except Exception as e:
            print(f"  OCR FAILED: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)

# Lazy-loaded PaddleOCR instance
_ocr_engine = None
_ocr_lock = threading.Lock()
_ocr_init_failed = False


def _get_ocr():
    """Get or create the PaddleOCR engine (thread-safe singleton)."""
    global _ocr_engine, _ocr_init_failed
    if _ocr_engine is not None:
        return _ocr_engine
    if _ocr_init_failed:
        return None
    with _ocr_lock:
        if _ocr_engine is not None:
            return _ocr_engine
        if _ocr_init_failed:
            return None

        result = [None]
        error = [None]

        def _init():
            try:
                from paddleocr import PaddleOCR
                result[0] = PaddleOCR(
                    use_angle_cls=True,
                    lang="chinese_cht",
                    show_log=False,
                    enable_mkldnn=False,
                )
            except Exception as e:
                error[0] = e

        init_thread = threading.Thread(target=_init, daemon=True)
        init_thread.start()
        init_thread.join(timeout=120)

        if init_thread.is_alive():
            logger.warning(
                "PaddleOCR initialization timed out (>120s). "
                "OCR is disabled. Scanned PDFs will not be indexed."
            )
            _ocr_init_failed = True
            return None

        if error[0] is not None:
            logger.warning(
                "PaddleOCR initialization failed: %s. "
                "Scanned PDFs will not be indexed.",
                error[0],
            )
            _ocr_init_failed = True
            return None

        if result[0] is not None:
            _ocr_engine = result[0]
            logger.info("PaddleOCR engine initialized (chinese_cht)")
            return _ocr_engine

        logger.warning("PaddleOCR initialization returned None")
        _ocr_init_failed = True
        return None


# Each worker process holds its own PaddleOCR instance
_worker_ocr = None


def _init_worker():
    """Initialize PaddleOCR once per worker process.

    On Windows, the module-level _patch_paddle_inference() runs when
    this module is re-imported in the spawned process, disabling OneDNN.
    Retries on PermissionError for model file-lock races.
    """
    global _worker_ocr
    # Disable OneDNN BEFORE importing paddle.
    # PaddlePaddle 3.x renamed FLAGS_use_mkldnn -> FLAGS_use_onednn;
    # set both for compatibility.
    os.environ['FLAGS_use_mkldnn'] = '0'
    os.environ['FLAGS_use_onednn'] = '0'
    from paddleocr import PaddleOCR
    import paddle
    paddle.set_flags({'FLAGS_use_mkldnn': False, 'FLAGS_use_onednn': False})
    for attempt in range(3):
        try:
            _worker_ocr = PaddleOCR(
                use_angle_cls=True, lang="chinese_cht", show_log=False,
                enable_mkldnn=False, use_gpu=False,
            )
            return
        except PermissionError:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                raise


def _render_and_ocr_worker(args: tuple) -> tuple[int, str]:
    """Render a page then OCR it. Runs in a worker process."""
    filepath, page_idx = args
    with fitz.open(filepath) as doc:
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")

    result = _worker_ocr.ocr(img_bytes)
    if not result or not result[0]:
        return (page_idx + 1, "")
    lines = [line[1][0] for line in result[0]]
    return (page_idx + 1, "\n".join(lines))


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
    text_pages: list[tuple[int, str]] = []
    ocr_page_indices: list[int] = []

    try:
        with fitz.open(filepath) as doc:
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

    # ── Parallel render + OCR via process pool ──────────────────────
    # Each worker process has its own PaddleOCR instance.
    # On Windows, the module-level _patch_paddle_inference() disables
    # OneDNN in each spawned worker.
    if ocr_page_indices:
        # Pre-download models in main process to avoid race conditions
        # when multiple workers try to download simultaneously.
        _get_ocr()

        num_workers = min(os.cpu_count() or 4, 8)
        logger.info(
            "Parallel render+OCR: %d pages, %d worker processes",
            len(ocr_page_indices), num_workers,
        )

        completed = 0
        with ProcessPoolExecutor(
            max_workers=num_workers, initializer=_init_worker
        ) as pool:
            tasks = [(filepath, idx) for idx in ocr_page_indices]
            future_to_idx = {
                pool.submit(_render_and_ocr_worker, task): task[1]
                for task in tasks
            }
            for future in as_completed(future_to_idx):
                try:
                    page_num, text = future.result()
                    if text:
                        text_pages.append((page_num, text))
                except Exception:
                    page_idx = future_to_idx[future]
                    logger.warning(
                        "Render+OCR failed for page %d",
                        page_idx + 1, exc_info=True,
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
