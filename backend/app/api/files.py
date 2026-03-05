"""File upload and management API endpoints."""

import logging
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse

from app.config import settings
from app.core.database import (
    clear_file_content,
    delete_file,
    get_file,
    insert_file,
    list_files,
    update_file_metadata,
    update_file_status,
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
    Progress is broadcast via the global /ws WebSocket endpoint.
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

    # Start background processing (progress broadcast via WebSocket)
    process_pdf_background(file_id, str(dest))

    return FileUploadResponse(
        id=file_id, filename=file.filename, status="processing"
    )


@router.get("/{file_id}/content")
async def get_file_content(file_id: int):
    """Serve the actual PDF file for the reader viewer."""
    f = get_file(file_id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    filepath = Path(f["filepath"]).resolve()
    upload_dir = Path(settings.upload_dir).resolve()
    # Ensure the file is within the upload directory (defense against path traversal)
    if not str(filepath).startswith(str(upload_dir)):
        raise HTTPException(status_code=403, detail="文件路径不合法")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在于磁盘")
    return FileResponse(
        str(filepath),
        media_type="application/pdf",
        filename=f["filename"],
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
    update_file_metadata(file_id, dynasty=req.dynasty, category=req.category, author=req.author)
    updated = get_file(file_id)
    if not updated:
        raise HTTPException(status_code=404, detail="文件不存在")
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


@router.post("/{file_id}/reindex")
async def reindex_file(file_id: int) -> dict:
    """Re-process a file (e.g. after OCR support is added)."""
    f = get_file(file_id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    filepath = f["filepath"]
    if not Path(filepath).exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在于磁盘")

    # Clear existing indexed content and reset status
    clear_file_content(file_id)
    update_file_status(file_id, "processing")

    process_pdf_background(file_id, filepath)
    return {"detail": "重新索引已开始", "file_id": file_id}
