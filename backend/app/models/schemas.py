"""Pydantic models for API request/response validation."""

from typing import Optional
from pydantic import BaseModel, Field


# ── File models ──────────────────────────────────────────────────────────────

class FileMetadata(BaseModel):
    id: int
    filename: str
    filepath: str
    dynasty: str = ""
    author: str = ""
    page_count: int = 0
    status: str = "pending"


class FileUploadResponse(BaseModel):
    id: int
    filename: str
    status: str


class FileListResponse(BaseModel):
    files: list[FileMetadata]
    total: int


class FileUpdateRequest(BaseModel):
    dynasty: Optional[str] = None
    author: Optional[str] = None


# ── Search models ────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    use_cbeta: bool = False
    session_id: Optional[int] = None


class SearchHit(BaseModel):
    source: str
    file_id: Optional[int] = None
    filename: Optional[str] = None
    page_num: Optional[int] = None
    snippet: str
    snippets: list[str] = []
    dynasty: str = ""
    author: str = ""
    sutra_id: Optional[str] = None
    title: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    traditional_query: str
    hits: list[SearchHit]
    total: int


# ── Chat models ──────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[int] = None
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str
    sources: list[SearchHit] = []


# ── Settings models ──────────────────────────────────────────────────────────

class LLMSettingsRequest(BaseModel):
    llm_provider: Optional[str] = None
    llm_provider_base_url: Optional[str] = None
    llm_provider_api_key: Optional[str] = None
    llm_model_name: Optional[str] = None


class LLMSettingsResponse(BaseModel):
    llm_provider: str
    llm_provider_base_url: str
    llm_model_name: str
    has_api_key: bool


# ── Session models ──────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)


class SessionResponse(BaseModel):
    id: int
    keyword: str
    traditional_keyword: str = ""
    synthesis: str = ""
    created_at: str
    updated_at: str
    message_count: int = 0


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int


class MessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


class SessionDetailResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]


# ── Search result storage models ──────────────────────────────────────────────

class SearchResultResponse(BaseModel):
    id: int
    session_id: int
    source: str
    file_id: Optional[int] = None
    filename: str = ""
    page_num: Optional[int] = None
    snippet: str = ""
    snippets: list[str] = []
    dynasty: str = ""
    author: str = ""
    sutra_id: Optional[str] = None
    title: Optional[str] = None
    created_at: str


class SessionSearchResultsResponse(BaseModel):
    session_id: int
    results: list[SearchResultResponse]
    total: int


# ── CBETA settings models ────────────────────────────────────────────────────

class AppSettingsResponse(BaseModel):
    cbeta_max_results: int = 20
    enable_thinking: bool = False


class AppSettingsUpdateRequest(BaseModel):
    cbeta_max_results: Optional[int] = Field(None, ge=5, le=100)
    enable_thinking: Optional[bool] = None
