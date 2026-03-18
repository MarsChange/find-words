"""Global WebSocket manager for broadcasting events to connected clients."""

import asyncio
import json
import logging
import threading
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# All connected WebSocket clients
_clients: set[WebSocket] = set()
_clients_lock = threading.Lock()

# Reference to the main asyncio event loop (set on first WS connect)
_main_loop: asyncio.AbstractEventLoop | None = None

# Allowed origins for WebSocket connections
_ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}


async def _safe_send_json(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    """Best-effort websocket send that won't raise on closed connections."""
    try:
        await websocket.send_json(payload)
        return True
    except Exception:
        logger.debug("WebSocket send skipped (connection closed): %s", payload.get("type"))
        return False


async def ws_endpoint(websocket: WebSocket) -> None:
    """Handle a WebSocket connection: accept, track, process messages."""
    global _main_loop
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin and origin not in _ALLOWED_ORIGINS:
        await websocket.close(code=4003)
        return

    await websocket.accept()

    # Capture the running event loop for cross-thread broadcasting
    _main_loop = asyncio.get_running_loop()

    with _clients_lock:
        _clients.add(websocket)
    logger.debug("WebSocket client connected (%d total)", len(_clients))
    try:
        # Process incoming messages
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "search_stream":
                # Handle streaming search request
                asyncio.create_task(_handle_search_stream(websocket, data))
            elif msg_type == "chat_stream":
                # Handle streaming chat request
                asyncio.create_task(_handle_chat_stream(websocket, data))
            # Ignore unknown message types
                
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        with _clients_lock:
            _clients.discard(websocket)
        logger.debug("WebSocket client disconnected (%d total)", len(_clients))


async def _handle_search_stream(websocket: WebSocket, data: dict) -> None:
    """Handle streaming search request."""
    from app.agents.agent_graph import run_search_streaming
    from app.core.database import insert_search_results, update_session_traditional_keyword, update_session_synthesis
    
    query = data.get("query", "")
    use_cbeta = data.get("use_cbeta", False)
    session_id = data.get("session_id")
    
    if not query or len(query) > 200:
        await _safe_send_json(websocket, {"type": "search_error", "error": "Query is required (max 200 chars)"})
        return
    
    try:
        # Send search started event
        await _safe_send_json(websocket, {"type": "search_started", "query": query})
        
        # Define chunk callback for streaming synthesis
        async def on_chunk(chunk: str):
            await _safe_send_json(websocket, {
                "type": "synthesis_chunk",
                "chunk": chunk,
                "session_id": session_id,
            })
        
        # Run search with streaming
        result = await asyncio.to_thread(
            run_search_streaming,
            query=query,
            use_cbeta=use_cbeta,
            on_chunk=lambda chunk: asyncio.run_coroutine_threadsafe(on_chunk(chunk), _main_loop) if _main_loop else None
        )
        
        # Store results in database if session_id provided
        if session_id:
            all_hits = result.get("all_hits", [])
            traditional_query = result.get("traditional_query", query)
            synthesis_text = result.get("synthesis", "")
            try:
                await asyncio.to_thread(insert_search_results, session_id, all_hits)
                await asyncio.to_thread(update_session_traditional_keyword, session_id, traditional_query)
                if synthesis_text:
                    await asyncio.to_thread(update_session_synthesis, session_id, synthesis_text)
            except Exception:
                # Persistence failure should not break the search response.
                logger.exception("Failed to persist search stream result (session_id=%s)", session_id)
        
        # Send completion event with all hits
        await _safe_send_json(websocket, {
            "type": "search_complete",
            "session_id": session_id,
            "traditional_query": result.get("traditional_query", query),
            "hits": result.get("all_hits", []),
            "synthesis": result.get("synthesis", ""),
        })
        
    except Exception:
        logger.exception("Search stream failed")
        await _safe_send_json(websocket, {"type": "search_error", "error": "Search failed"})


async def _handle_chat_stream(websocket: WebSocket, data: dict) -> None:
    """Handle streaming chat request."""
    from app.agents.agent_graph import run_chat_streaming
    from app.core.database import add_message, get_session_by_id
    
    message = data.get("message", "")
    session_id = data.get("session_id")
    history = data.get("history", [])
    synthesis = data.get("synthesis", "")
    
    if not message or len(message) > 10000:
        await _safe_send_json(websocket, {"type": "chat_error", "error": "Message is required (max 10000 chars)"})
        return
    
    # Validate session if provided
    if session_id:
        try:
            session = await asyncio.to_thread(get_session_by_id, session_id)
            if not session:
                await _safe_send_json(websocket, {"type": "chat_error", "error": "Session not found"})
                return
            # Store user message
            await asyncio.to_thread(add_message, session_id, "user", message)
        except Exception:
            logger.exception("Failed to validate session or store message")
    
    try:
        # Send chat started event
        await _safe_send_json(websocket, {"type": "chat_started", "session_id": session_id})
        
        # Define chunk callback for streaming
        async def on_chunk(chunk: str):
            await _safe_send_json(websocket, {
                "type": "chat_chunk",
                "chunk": chunk,
                "session_id": session_id,
            })
        
        # Run chat with streaming
        reply = await asyncio.to_thread(
            run_chat_streaming,
            message=message,
            history=history,
            session_id=session_id,
            synthesis=synthesis,
            on_chunk=lambda chunk: asyncio.run_coroutine_threadsafe(on_chunk(chunk), _main_loop) if _main_loop else None
        )
        
        # Store assistant reply if session provided
        if session_id:
            await asyncio.to_thread(add_message, session_id, "assistant", reply)
        
        # Send completion event
        await _safe_send_json(websocket, {
            "type": "chat_complete",
            "session_id": session_id,
            "reply": reply,
        })
        
    except Exception:
        logger.exception("Chat stream failed")
        await _safe_send_json(websocket, {"type": "chat_error", "error": "Chat failed"})


async def _broadcast(data: dict[str, Any]) -> None:
    """Send a JSON message to all connected clients."""
    with _clients_lock:
        targets = list(_clients)
    if not targets:
        return
    dead: list[WebSocket] = []
    for ws in targets:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    if dead:
        with _clients_lock:
            for ws in dead:
                _clients.discard(ws)


def broadcast_sync(data: dict[str, Any]) -> None:
    """Thread-safe broadcast — can be called from any thread.

    Schedules the async broadcast on the main event loop.
    """
    if _main_loop is None or _main_loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast(data), _main_loop)
    except Exception:
        pass
