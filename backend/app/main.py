"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.core.database import init_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup."""
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url="/api/redoc" if settings.debug else None,
)

# CORS - allow frontend dev server and Electron app
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
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
