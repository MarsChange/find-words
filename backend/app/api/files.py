"""File upload and management API endpoints with WebSocket progress."""

import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

from app.config import settings
from app.core.database import (
    delete_file,
    get_file,
    insert_file,
    list_files,
    update_file_metadata,
)
from app.models.schemas import (
    FileListResponse,
    FileMetadata,
    FileUpdateRequest,
    FileUploadResponse,
)
from app.services.pdf_processor import process_pdf_background

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

# Active WebSocket connections for progress updates
_progress_sockets: dict[int, WebSocket] = {}

# Maximum upload size: 1024 MB
_MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


@router.get("", response_model=FileListResponse)
async def get_files() -> FileListResponse:
    """List all uploaded files."""
    files = list_files()
    items = [FileMetadata(**f) for f in files]
    return FileListResponse(files=items, total=len(items))


@router.post("", response_model=FileUploadResponse)
async def upload_file(file: UploadFile) -> FileUploadResponse:
    """
    Upload a PDF file for indexing.

    The file is saved to disk and processing starts in a background thread.
    Connect to the WebSocket endpoint to receive progress updates.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    # Validate content type
    if file.content_type not in ("application/pdf", "application/octet-stream", None):
        raise HTTPException(status_code=400, detail="文件类型不正确，仅支持 PDF")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Save with a UUID-only name to prevent path traversal via filename
    safe_name = f"{uuid.uuid4().hex}.pdf"
    dest = upload_dir / safe_name

    content = await file.read()

    # Enforce file size limit
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，最大允许 {_MAX_UPLOAD_BYTES // (1024*1024)} MB",
        )

    # Validate PDF magic bytes
    if not content[:5].startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="文件内容不是有效的 PDF")

    dest.write_bytes(content)

    file_id = insert_file(filename=file.filename, filepath=str(dest))

    # Define a progress callback that pushes to WebSocket
    def _progress(current: int, total: int) -> None:
        ws = _progress_sockets.get(file_id)
        if ws:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    ws.send_json(
                        {"file_id": file_id, "current": current, "total": total}
                    )
                )
                loop.close()
            except Exception:
                pass

    process_pdf_background(file_id, str(dest), progress_callback=_progress)

    return FileUploadResponse(
        id=file_id, filename=file.filename, status="processing"
    )


@router.get("/{file_id}", response_model=FileMetadata)
async def get_file_detail(file_id: int) -> FileMetadata:
    """Get metadata for a single file."""
    f = get_file(file_id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileMetadata(**f)


@router.patch("/{file_id}", response_model=FileMetadata)
async def update_file(file_id: int, req: FileUpdateRequest) -> FileMetadata:
    """Update file metadata (dynasty, author)."""
    f = get_file(file_id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    update_file_metadata(file_id, dynasty=req.dynasty, author=req.author)
    updated = get_file(file_id)
    return FileMetadata(**updated)


@router.delete("/{file_id}")
async def remove_file(file_id: int) -> dict:
    """Delete a file and its indexed content."""
    f = get_file(file_id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    # Remove from disk
    try:
        filepath = Path(f["filepath"])
        if filepath.exists():
            filepath.unlink()
    except OSError:
        logger.warning("Could not delete file on disk: %s", f["filepath"])
    delete_file(file_id)
    return {"detail": "文件已删除"}


_ALLOWED_WS_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


@router.websocket("/ws/progress/{file_id}")
async def file_progress_ws(websocket: WebSocket, file_id: int) -> None:
    """WebSocket endpoint for real-time file processing progress."""
    # Validate origin to prevent cross-site WebSocket hijacking
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin and origin not in _ALLOWED_WS_ORIGINS:
        await websocket.close(code=4003)
        return

    await websocket.accept()
    _progress_sockets[file_id] = websocket
    try:
        # Keep connection alive until client disconnects or file is done
        while True:
            f = get_file(file_id)
            if f and f["status"] in ("ready", "error"):
                await websocket.send_json(
                    {"file_id": file_id, "status": f["status"]}
                )
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        _progress_sockets.pop(file_id, None)
