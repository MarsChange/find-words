"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.core.database import init_db, recover_stuck_files

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup and recover stuck files."""
    init_db()

    # Recover files stuck at 'processing' from a previous crash / failed OCR
    stuck_files = recover_stuck_files()
    if stuck_files:
        from app.services.pdf_processor import process_pdf_background
        for f in stuck_files:
            fpath = f["filepath"]
            if Path(fpath).exists():
                logger.info(
                    "Re-processing stuck file: id=%d, %s", f["id"], f["filename"]
                )
                process_pdf_background(f["id"], fpath)
            else:
                logger.warning(
                    "Stuck file missing on disk, marking as error: id=%d, %s",
                    f["id"], f["filename"],
                )
                from app.core.database import update_file_status
                update_file_status(f["id"], "error")

    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url="/api/redoc" if settings.debug else None,
)

# CORS - allow frontend dev server and Electron app (any localhost port)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# Register API routers
from app.api.search import router as search_router
from app.api.files import router as files_router
from app.api.chat import router as chat_router
from app.api.settings import router as settings_router

app.include_router(search_router)
app.include_router(files_router)
app.include_router(chat_router)
app.include_router(settings_router)

# Global WebSocket endpoint for real-time events
from app.core.ws_manager import ws_endpoint

@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    await ws_endpoint(websocket)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "app": settings.app_name}


# ── Serve frontend static files in production (Electron) mode ────────────────

_static_dir = Path(settings.static_dir) if settings.static_dir else None

if _static_dir and _static_dir.is_dir():
    # Serve assets (JS, CSS, images) under /assets
    assets_dir = _static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # SPA fallback: any non-API route serves index.html
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the frontend SPA for any non-API route."""
        file_path = (_static_dir / full_path).resolve()
        # Prevent path traversal outside the static directory
        if file_path.is_file() and str(file_path).startswith(str(_static_dir.resolve())):
            return FileResponse(str(file_path))
        return FileResponse(str(_static_dir / "index.html"))
