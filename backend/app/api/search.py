"""Search API endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from app.agents.agent_graph import run_search
from app.core.database import insert_search_results, update_session_traditional_keyword
from app.models.schemas import SearchHit, SearchRequest, SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    """
    Run a full-text search across local indexed files and optionally CBETA.

    The query is automatically converted from simplified to traditional Chinese.
    """
    try:
        result = run_search(query=req.query, use_cbeta=req.use_cbeta)
    except Exception:
        logger.exception("Search failed for query: %s", req.query)
        raise HTTPException(status_code=500, detail="搜索处理失败")

    all_hits = result.get("all_hits", [])

    hits = [
        SearchHit(
            source=h.get("source", "local"),
            file_id=int(h["file_id"]) if h.get("file_id") else None,
            filename=h.get("filename", ""),
            page_num=int(h["page_num"]) if h.get("page_num") else None,
            snippet=h.get("snippet", ""),
            snippets=h.get("snippets", []),
            dynasty=h.get("dynasty", ""),
            author=h.get("author", ""),
            sutra_id=h.get("sutra_id"),
            title=h.get("title"),
        )
        for h in all_hits
    ]

    # Persist search results to the database if a session_id was provided
    if req.session_id is not None:
        try:
            insert_search_results(req.session_id, all_hits)
        except Exception:
            logger.exception("Failed to store search results for session %s", req.session_id)
        try:
            traditional_query = result.get("traditional_query", req.query)
            update_session_traditional_keyword(req.session_id, traditional_query)
        except Exception:
            logger.exception("Failed to store traditional_keyword for session %s", req.session_id)

    return SearchResponse(
        query=req.query,
        traditional_query=result.get("traditional_query", req.query),
        hits=hits,
        total=len(hits),
    )
