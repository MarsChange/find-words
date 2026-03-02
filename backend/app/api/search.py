"""Search API endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from app.agents.agent_graph import run_search
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

    hits = [
        SearchHit(
            source=h.get("source", "local"),
            file_id=int(h["file_id"]) if h.get("file_id") else None,
            filename=h.get("filename", ""),
            page_num=int(h["page_num"]) if h.get("page_num") else None,
            snippet=h.get("snippet", ""),
            dynasty=h.get("dynasty", ""),
            author=h.get("author", ""),
        )
        for h in result.get("all_hits", [])
    ]

    return SearchResponse(
        query=req.query,
        traditional_query=result.get("traditional_query", req.query),
        hits=hits,
        total=len(hits),
    )
