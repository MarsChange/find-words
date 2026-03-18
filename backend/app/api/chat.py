"""Chat and session management API endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from app.agents.agent_graph import run_chat, run_search
from app.config import settings
from app.core.database import (
    add_message,
    create_session,
    delete_session,
    get_messages_by_session,
    get_search_results_by_session,
    get_session_by_id,
    get_sessions,
)
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    MessageResponse,
    SearchHit,
    SearchResultResponse,
    SessionCreate,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
    SessionSearchResultsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


# ── Session endpoints ────────────────────────────────────────────────────────

@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions() -> SessionListResponse:
    """List all chat sessions ordered by most recent first."""
    rows = get_sessions()
    items = [SessionResponse(**r) for r in rows]
    return SessionListResponse(sessions=items, total=len(items))


@router.post("/sessions", response_model=SessionResponse)
async def create_new_session(req: SessionCreate) -> SessionResponse:
    """Create a new chat session with the given keyword."""
    row = create_session(keyword=req.keyword)
    # Fetch with message_count included
    full = get_session_by_id(row["id"])
    return SessionResponse(**full)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(session_id: int) -> SessionDetailResponse:
    """Get a session and all its messages."""
    session = get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = get_messages_by_session(session_id)
    return SessionDetailResponse(
        session=SessionResponse(**session),
        messages=[MessageResponse(**m) for m in messages],
    )


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: int) -> dict:
    """Delete a session and all its messages."""
    session = get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    delete_session(session_id)
    return {"detail": "会话已删除"}


@router.get("/sessions/{session_id}/results", response_model=SessionSearchResultsResponse)
async def get_session_results(session_id: int) -> SessionSearchResultsResponse:
    """Get all search results stored for a session."""
    session = get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = get_search_results_by_session(session_id)
    results = [SearchResultResponse(**r) for r in rows]
    return SessionSearchResultsResponse(
        session_id=session_id,
        results=results,
        total=len(results),
    )


# ── Chat endpoint ────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Send a message and receive an AI-generated reply.

    If session_id is provided, the conversation is persisted to that session
    and prior messages are loaded as context. Otherwise, the client-supplied
    history list is used.
    """
    if not settings.llm_provider_api_key:
        raise HTTPException(
            status_code=400,
            detail="LLM 未配置。请在设置页面中填写 API Key。",
        )

    # Build history from session or from the request body
    if req.session_id is not None:
        session = get_session_by_id(req.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        db_messages = get_messages_by_session(req.session_id)
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in db_messages
        ]
        # Persist the user message
        add_message(req.session_id, "user", req.message)
    else:
        history = [
            {"role": m.role, "content": m.content} for m in req.history
        ]

    try:
        # Run a search to gather context
        search_result = run_search(query=req.message, use_cbeta=False)
        hits = search_result.get("all_hits", [])

        # Enrich chat history with search context if available
        if hits:
            context_lines = [
                f"[{h.get('filename', '')}] {h.get('snippet', '')}"
                for h in hits[:10]
            ]
            context_block = (
                "以下是相关的检索结果供参考：\n"
                + "\n".join(context_lines)
                + "\n\n用户问题："
                + req.message
            )
            reply = run_chat(context_block, history)
        else:
            reply = run_chat(req.message, history)

        # Persist the assistant reply if using a session
        if req.session_id is not None:
            add_message(req.session_id, "assistant", reply)

        sources = [
            SearchHit(
                source=h.get("source", "local"),
                file_id=int(h["file_id"]) if h.get("file_id") else None,
                filename=h.get("filename", ""),
                page_num=int(h["page_num"]) if h.get("page_num") else None,
                snippet=h.get("snippet", ""),
                snippets=h.get("snippets", []),
                keyword_sentence=h.get("keyword_sentence", ""),
                is_original_text=bool(h.get("is_original_text", False)),
                content_label=h.get("content_label", ""),
                dynasty=h.get("dynasty", ""),
                category=h.get("category", ""),
                author=h.get("author", ""),
            )
            for h in hits[:5]
        ]

        return ChatResponse(reply=reply, sources=sources)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat processing failed")
        raise HTTPException(status_code=500, detail="对话处理失败")
