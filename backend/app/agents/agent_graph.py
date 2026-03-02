"""LangGraph multi-agent workflow for classical text search and analysis."""

import logging
from dataclasses import dataclass, field
from typing import Annotated, TypedDict

import opencc
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from app.core.database import search_content, get_messages_by_session
from app.services.cbeta_scraper import search_cbeta

logger = logging.getLogger(__name__)

# Shared OpenCC converter: Simplified -> Traditional
_s2t = opencc.OpenCC("s2t")
_t2s = opencc.OpenCC("t2s")


# ── State definition ─────────────────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    """Shared state flowing through the agent graph."""
    original_query: str
    traditional_query: str
    use_cbeta: bool
    local_hits: list[dict]
    cbeta_hits: list[dict]
    all_hits: list[dict]
    synthesis: str
    chat_history: list[dict]
    chat_reply: str


# ── Node functions ───────────────────────────────────────────────────────────

def query_processor(state: AgentState) -> AgentState:
    """Convert the query from simplified to traditional Chinese."""
    original = state["original_query"]
    traditional = _s2t.convert(original)
    logger.info("Query: %s -> %s", original, traditional)
    return {**state, "traditional_query": traditional}


def local_searcher(state: AgentState) -> AgentState:
    """Search the local SQLite FTS5 index."""
    query = state["traditional_query"]
    # Also search the original (simplified) form
    original = state["original_query"]

    hits = search_content(query)
    if original != query:
        hits.extend(search_content(original))

    # Deduplicate by (file_id, page_num)
    seen = set()
    unique: list[dict] = []
    for h in hits:
        key = (h.get("file_id"), h.get("page_num"))
        if key not in seen:
            seen.add(key)
            unique.append(h)

    return {**state, "local_hits": unique}


def cbeta_scraper_node(state: AgentState) -> AgentState:
    """Optionally scrape CBETA online for additional results."""
    if not state.get("use_cbeta", False):
        return {**state, "cbeta_hits": []}

    query = state["traditional_query"]
    try:
        results = search_cbeta(query)
        hits = [
            {
                "source": "cbeta",
                "filename": r.title,
                "snippet": r.snippet,
                "dynasty": "",
                "author": "",
                "sutra_id": r.sutra_id,
            }
            for r in results
        ]
    except Exception:
        logger.exception("CBETA scraper failed")
        hits = []

    return {**state, "cbeta_hits": hits}


def synthesizer(state: AgentState) -> AgentState:
    """Merge local and CBETA hits, optionally call LLM for synthesis."""
    import app.config as cfg

    local = state.get("local_hits", [])
    cbeta = state.get("cbeta_hits", [])

    # Tag local hits
    for h in local:
        h.setdefault("source", "local")

    all_hits = local + cbeta

    # If LLM is configured, produce a synthesis
    synthesis = ""
    if cfg.settings.llm_provider_api_key and all_hits:
        try:
            llm = _get_llm()
            excerpts = "\n".join(
                f"- [{h.get('source')}] {h.get('filename', '')}: {h.get('snippet', '')}"
                for h in all_hits[:20]
            )
            messages = [
                SystemMessage(content=(
                    "你是一位古籍研究助手。根据以下检索结果，"
                    "总结该词语在古籍中的出处和上下文含义，按朝代排序。"
                    "使用繁体中文回答。"
                )),
                HumanMessage(content=(
                    f"检索词：{state['traditional_query']}\n\n"
                    f"检索结果：\n{excerpts}"
                )),
            ]
            resp = llm.invoke(messages)
            synthesis = resp.content
        except Exception:
            logger.exception("LLM synthesis failed")

    return {**state, "all_hits": all_hits, "synthesis": synthesis}


def chat_agent(state: AgentState) -> AgentState:
    """Handle multi-turn chat follow-up questions using LLM."""
    import app.config as cfg

    if not cfg.settings.llm_provider_api_key:
        return {**state, "chat_reply": "LLM 未配置，请在设置中添加 API Key。"}

    history = state.get("chat_history", [])
    if not history:
        return state

    try:
        llm = _get_llm()
        messages = [
            SystemMessage(content=(
                "你是古籍研究助手，帮助用户查找和分析古典文献中的词语。"
                "用繁体中文回答。如需搜索可告知用户使用搜索功能。"
            ))
        ]
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))

        resp = llm.invoke(messages)
        return {**state, "chat_reply": resp.content}
    except Exception:
        logger.exception("Chat agent failed")
        return {**state, "chat_reply": "抱歉，处理请求时出错，请稍后再试。"}


# ── Helper ───────────────────────────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    """Create an OpenAI-compatible LLM client from current settings.

    All supported providers (DeepSeek, Qwen, Kimi, MiniMax) expose
    OpenAI-compatible endpoints, so we use ChatOpenAI for all of them.
    """
    import app.config as cfg

    current = cfg.settings
    if not current.llm_provider_api_key:
        raise ValueError("LLM API Key 未配置")
    return ChatOpenAI(
        model=current.llm_model_name,
        api_key=current.llm_provider_api_key,
        base_url=current.llm_provider_base_url or None,
    )


# ── Graph construction ───────────────────────────────────────────────────────

def build_search_graph() -> StateGraph:
    """Build and compile the search workflow graph."""
    graph = StateGraph(AgentState)

    graph.add_node("query_processor", query_processor)
    graph.add_node("local_searcher", local_searcher)
    graph.add_node("cbeta_scraper", cbeta_scraper_node)
    graph.add_node("synthesizer", synthesizer)

    graph.set_entry_point("query_processor")
    graph.add_edge("query_processor", "local_searcher")
    graph.add_edge("query_processor", "cbeta_scraper")
    graph.add_edge("local_searcher", "synthesizer")
    graph.add_edge("cbeta_scraper", "synthesizer")
    graph.add_edge("synthesizer", END)

    return graph.compile()


def build_chat_graph() -> StateGraph:
    """Build and compile the chat workflow graph."""
    graph = StateGraph(AgentState)

    graph.add_node("chat_agent", chat_agent)

    graph.set_entry_point("chat_agent")
    graph.add_edge("chat_agent", END)

    return graph.compile()


# Pre-compiled graphs (lazily used)
search_graph = build_search_graph()
chat_graph = build_chat_graph()


# ── Public API ───────────────────────────────────────────────────────────────

def run_search(query: str, use_cbeta: bool = False) -> dict:
    """Execute the full search pipeline and return results."""
    state: AgentState = {
        "original_query": query,
        "traditional_query": "",
        "use_cbeta": use_cbeta,
        "local_hits": [],
        "cbeta_hits": [],
        "all_hits": [],
        "synthesis": "",
    }
    result = search_graph.invoke(state)
    return result


def run_chat(message: str, history: list[dict],
             session_id: int | None = None) -> str:
    """
    Run a chat turn and return the assistant reply.

    If session_id is provided and history is empty, messages are loaded
    from the database for that session.
    """
    if session_id is not None and not history:
        db_msgs = get_messages_by_session(session_id)
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in db_msgs
        ]
    full_history = history + [{"role": "user", "content": message}]
    state: AgentState = {
        "original_query": message,
        "chat_history": full_history,
        "chat_reply": "",
    }
    result = chat_graph.invoke(state)
    return result.get("chat_reply", "")
