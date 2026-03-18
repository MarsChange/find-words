"""LangGraph multi-agent workflow for classical text search and analysis."""

import json
import logging
import operator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, TypedDict

from app.core.database import search_content, get_messages_by_session, get_setting

logger = logging.getLogger(__name__)
_JUDGE_MAX_WORKERS = 8


# ── Lazy-loaded heavy dependencies ──────────────────────────────────────────
# opencc, openai, langgraph, and cbeta_scraper are imported only when first
# needed, shaving several seconds off server startup time.

_s2t = None
_t2s = None


def _get_s2t():
    global _s2t
    if _s2t is None:
        import opencc
        _s2t = opencc.OpenCC("s2t")
    return _s2t


def _get_t2s():
    global _t2s
    if _t2s is None:
        import opencc
        _t2s = opencc.OpenCC("t2s")
    return _t2s


# ── State definition ─────────────────────────────────────────────────────────

class _AgentStateRequired(TypedDict):
    """Required keys for AgentState."""
    original_query: str


class AgentState(_AgentStateRequired, total=False):
    """Shared state flowing through the agent graph."""
    traditional_query: str
    use_cbeta: bool
    local_hits: Annotated[list[dict], operator.add]
    cbeta_hits: Annotated[list[dict], operator.add]
    all_hits: Annotated[list[dict], operator.add]
    synthesis: str
    chat_history: list[dict]
    chat_reply: str


# ── Node functions ───────────────────────────────────────────────────────────

def query_processor(state: AgentState) -> dict:
    """Convert the query from simplified to traditional Chinese."""
    original = state["original_query"]
    traditional = _get_s2t().convert(original)
    logger.info("Query: %s -> %s", original, traditional)
    return {"traditional_query": traditional}


def local_searcher(state: AgentState) -> dict:
    """Search the local SQLite FTS5 index."""
    query = state.get("traditional_query", state["original_query"])
    # Also search the original (simplified) form
    original = state["original_query"]

    hits = search_content(query)
    if original != query:
        hits.extend(search_content(original))

    # Deduplicate by occurrence granularity
    seen = set()
    unique: list[dict] = []
    for h in hits:
        key = (
            h.get("file_id"),
            h.get("page_num"),
            h.get("snippet", ""),
            h.get("keyword_sentence", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(h)

    # Post-classify local hits via web search, tagging entries that are likely
    # original classical text body ("正文").
    return {"local_hits": _annotate_local_hits_with_web_search(unique, query)}


def cbeta_scraper_node(state: AgentState) -> dict:
    """Optionally scrape CBETA online for additional results."""
    if not state.get("use_cbeta", False):
        return {"cbeta_hits": []}

    from app.services.cbeta_scraper import search_cbeta

    query = state.get("traditional_query", state["original_query"])
    try:
        # Read max_results from DB settings (default 20)
        val = get_setting("cbeta_max_results")
        max_results = int(val) if val else 20
        results = search_cbeta(query, max_results=max_results)
        raw_hits = [
            {
                "source": "cbeta",
                "filename": r.title,
                "snippet": r.snippets[0] if r.snippets else "",
                "snippets": r.snippets,
                "dynasty": r.dynasty,
                "author": r.author,
                "sutra_id": r.sutra_id,
                "title": r.title,
            }
            for r in results
        ]
        hits = _merge_cbeta_hits(raw_hits)
    except Exception:
        logger.exception("CBETA scraper failed")
        hits = []

    return {"cbeta_hits": hits}


def synthesizer(state: AgentState) -> dict:
    """Merge local and CBETA hits, call LLM for synthesis."""
    import app.config as cfg

    local = list(state.get("local_hits", []))
    cbeta = list(state.get("cbeta_hits", []))

    # Tag local hits
    for h in local:
        h.setdefault("source", "local")

    all_hits = local + cbeta

    # If LLM is configured, produce a synthesis
    synthesis = ""
    if cfg.settings.llm_provider_api_key and all_hits:
        try:
            client = _get_client()
            excerpts = "\n".join(_format_excerpt(h) for h in _hits_for_llm_context(all_hits)[:20])
            messages: list = [
                {"role": "system", "content": (
                    "你是一位汉语言古籍研究助手。目前用户检索相应的词语文语料，得到了以下检索结果，"
                    f"检索词：{state.get('traditional_query', '')}\n"
                    f"检索结果：\n{excerpts}"
                    "\n\n务必注意回答的专业性和准确性，并适当结合检索结果的例句，以及联网搜索得到的相关资料，理解该词语在古籍中的出处和上下文含义，根据用户的输入，为用户提供专业化的分析。"
                )},
                {"role": "user", "content": (
                    "请你从汉语词汇史的角度梳理并分析用户所检索词语的中土化路径。\n"
                )},
            ]
            extra_kwargs = _thinking_kwargs()
            resp = client.chat.completions.create(
                model=cfg.settings.llm_model_name,
                messages=messages,
                **extra_kwargs,
            )
            synthesis = resp.choices[0].message.content
        except Exception:
            logger.exception("LLM synthesis failed")

    return {"all_hits": all_hits, "synthesis": synthesis}


def synthesizer_streaming(state: AgentState, on_chunk=None):
    """Merge local and CBETA hits, call LLM for streaming synthesis.
    
    Args:
        state: Agent state
        on_chunk: Optional callback(chunk_text: str) called for each token
    
    Returns:
        dict with all_hits and synthesis (full text)
    """
    import app.config as cfg

    local = list(state.get("local_hits", []))
    cbeta = list(state.get("cbeta_hits", []))

    # Tag local hits
    for h in local:
        h.setdefault("source", "local")

    all_hits = local + cbeta

    # If LLM is configured, produce a synthesis
    synthesis = ""
    if cfg.settings.llm_provider_api_key and all_hits:
        try:
            client = _get_client()
            excerpts = "\n".join(_format_excerpt(h) for h in _hits_for_llm_context(all_hits)[:20])
            messages: list = [
                {"role": "system", "content": (
                    "你是一位汉语言古籍研究助手。目前用户检索相应的词语文语料，得到了以下检索结果，"
                    f"检索词：{state.get('traditional_query', '')}\n"
                    f"检索结果：\n{excerpts}"
                    "\n\n务必注意回答的专业性和准确性，并适当结合检索结果的例句，以及联网搜索得到的相关资料，理解该词语在古籍中的出处和上下文含义，根据用户的输入，为用户提供专业化的分析。"
                )},
                {"role": "user", "content": (
                    "请从汉语词汇史的角度，结合汉译佛典和本土文献语料，梳理并分析用户所检索词语的中土化路径。\n"
                )},
            ]
            extra_kwargs = _thinking_kwargs()
            stream = client.chat.completions.create(
                model=cfg.settings.llm_model_name,
                messages=messages,
                stream=True,
                **extra_kwargs,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    synthesis += content
                    if on_chunk:
                        on_chunk(content)
        except Exception:
            logger.exception("LLM streaming synthesis failed")

    return {"all_hits": all_hits, "synthesis": synthesis}


def chat_agent(state: AgentState) -> dict:
    """Handle multi-turn chat follow-up questions using LLM."""
    import app.config as cfg

    if not cfg.settings.llm_provider_api_key:
        return {"chat_reply": "LLM 未配置，请在设置中添加 API Key。"}

    history = state.get("chat_history", [])
    if not history:
        return {}
    local = list(state.get("local_hits", []))
    cbeta = list(state.get("cbeta_hits", []))

    # Tag local hits
    for h in local:
        h.setdefault("source", "local")

    all_hits = local + cbeta
    excerpts = "\n".join(_format_excerpt(h) for h in _hits_for_llm_context(all_hits)[:20])
    try:
        client = _get_client()
        messages: list = [
            {"role": "system", "content": (
                    "你是一位汉语言古籍研究助手。目前用户检索相应的词语文语料，得到了以下检索结果，"
                    f"检索词：{state.get('traditional_query', '')}\n"
                    f"检索结果：\n{excerpts}"
                    "\n\n务必注意回答的专业性和准确性，并适当结合检索结果的例句，以及联网搜索得到的相关资料，理解该词语在古籍中的出处和上下文含义，根据用户的输入，为用户提供专业化的分析。"
            )}
        ]
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        extra_kwargs = _thinking_kwargs()
        resp = client.chat.completions.create(
            model=cfg.settings.llm_model_name,
            messages=messages,
            **extra_kwargs,
        )
        return {"chat_reply": resp.choices[0].message.content}
    except Exception:
        logger.exception("Chat agent failed")
        return {"chat_reply": "抱歉，处理请求时出错，请稍后再试。"}


# ── Helper ───────────────────────────────────────────────────────────────────

def _format_excerpt(h: dict) -> str:
    """Format a single hit as a labelled excerpt line for LLM context."""
    source = h.get("source", "local")
    if source == "local":
        label = "正文" if h.get("is_original_text", False) else "未核正文"
        dynasty = h.get("dynasty", "") or "朝代未详"
        category = h.get("category", "") or "来源未详"
        tag = f"[local/{label}/{dynasty}/{category}]"
    else:
        tag = f"[{source}]"
    return f"- {tag} {h.get('filename', '')}: {h.get('snippet', '')}"


def _hits_for_llm_context(hits: list[dict]) -> list[dict]:
    """Filter hits for LLM prompt: local only keeps web-verified 正文."""
    return [
        h for h in hits
        if h.get("source") != "local" or h.get("is_original_text", False)
    ]


def _merge_cbeta_hits(hits: list[dict]) -> list[dict]:
    """Merge CBETA hits by catalog key; keep snippets aggregated."""
    merged: dict[tuple[str, str, str, str], dict] = {}

    for h in hits:
        key = (
            str(h.get("sutra_id", "")),
            str(h.get("title", "") or h.get("filename", "")),
            str(h.get("dynasty", "")),
            str(h.get("author", "")),
        )
        if key not in merged:
            item = dict(h)
            snippets = list(item.get("snippets", [])) or (
                [item.get("snippet", "")] if item.get("snippet", "") else []
            )
            item["snippets"] = snippets
            item["snippet"] = snippets[0] if snippets else item.get("snippet", "")
            merged[key] = item
            continue

        target = merged[key]
        existing = list(target.get("snippets", []))
        incoming = list(h.get("snippets", [])) or (
            [h.get("snippet", "")] if h.get("snippet", "") else []
        )
        for s in incoming:
            if s and s not in existing:
                existing.append(s)
        target["snippets"] = existing
        if existing:
            target["snippet"] = existing[0]

    return list(merged.values())


def _extract_json_object(text: str) -> dict:
    """Best-effort extraction of a JSON object from model output."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _web_search_model() -> str:
    """Choose a Qwen model for web-search-based sentence judgement."""
    configured = get_setting("ocr_model") or "qwen3.5-plus"
    if configured.lower().startswith("qwen"):
        return configured
    return "qwen3.5-plus"


def _judge_sentence_is_original_text(sentence: str, query: str) -> tuple[bool, str]:
    """Use Qwen web search to judge whether a sentence is original text."""
    client = _get_client()
    model = _web_search_model()
    messages = [
        {
            "role": "system",
            "content": (
                "你是古籍正文判定助手。你必须联网检索，并重点使用“句子+原文”进行搜索。"
                "仅返回 JSON："
                "{\"is_original_text\":true/false,\"reason\":\"简短理由\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"检索词：{query}\n"
                f"待判定句子：{sentence}\n"
                f"请至少执行一次检索：{sentence} 原文\n"
                "请通过联网搜索判断这句是否属于古籍原始正文，而不是注文、注释或后人案语。"
            ),
        },
    ]
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        extra_body={"enable_search": True, "enable_thinking": False},
    )
    data = _extract_json_object(resp.choices[0].message.content or "")
    raw_flag = data.get("is_original_text", False)
    if isinstance(raw_flag, bool):
        is_original = raw_flag
    else:
        is_original = str(raw_flag).strip().lower() in {"true", "1", "yes", "是"}
    reason = str(data.get("reason", "")).strip()
    return is_original, reason


def _annotate_local_hits_with_web_search(hits: list[dict], query: str) -> list[dict]:
    """Classify local hits as 正文/非正文 with parallel web-search judgement."""
    if not hits:
        return []

    sentence_cache: dict[str, tuple[bool, str]] = {}
    unique_sentences: list[str] = []
    for h in hits:
        sentence = str(h.get("keyword_sentence") or h.get("snippet") or "").strip()
        if not sentence:
            h["is_original_text"] = False
            h["content_label"] = "未核正文"
            continue
        if sentence not in sentence_cache:
            sentence_cache[sentence] = (False, "")
            unique_sentences.append(sentence)

    if unique_sentences:
        num_workers = min(_JUDGE_MAX_WORKERS, len(unique_sentences))
        logger.info(
            "Parallel正文判定: %d sentences, %d threads",
            len(unique_sentences),
            num_workers,
        )
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            future_to_sentence = {
                pool.submit(_judge_sentence_is_original_text, sentence, query): sentence
                for sentence in unique_sentences
            }
            for future in as_completed(future_to_sentence):
                sentence = future_to_sentence[future]
                try:
                    sentence_cache[sentence] = future.result()
                except Exception:
                    logger.exception("Web-search sentence judgement failed")
                    sentence_cache[sentence] = (False, "")

    for h in hits:
        sentence = str(h.get("keyword_sentence") or h.get("snippet") or "").strip()
        if not sentence:
            continue
        is_original, reason = sentence_cache.get(sentence, (False, ""))
        h["is_original_text"] = is_original
        h["content_label"] = "正文" if is_original else "未核正文"
        h["judgement_reason"] = reason

    return hits


def _get_client():
    """Create an OpenAI-compatible client from current settings.

    All supported providers (DeepSeek, Qwen, Kimi, MiniMax) expose
    OpenAI-compatible endpoints, so we use the openai SDK for all of them.
    """
    import app.config as cfg
    from openai import OpenAI

    current = cfg.settings
    if not current.llm_provider_api_key:
        raise ValueError("LLM API Key 未配置")
    return OpenAI(
        api_key=current.llm_provider_api_key,
        base_url=current.llm_provider_base_url or None,
    )


def _thinking_kwargs() -> dict:
    """Return extra kwargs for chat.completions.create when thinking mode is on."""
    enable_thinking = get_setting("enable_thinking")
    if enable_thinking == "true":
        return {"extra_body": {"enable_thinking": True, "enable_search": True}}
    return {"extra_body": {"enable_thinking": False, "enable_search": True}}


# ── Graph construction ───────────────────────────────────────────────────────

def build_search_graph():
    """Build and compile the search workflow graph."""
    from langgraph.graph import END, StateGraph

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


def build_chat_graph():
    """Build and compile the chat workflow graph."""
    from langgraph.graph import END, StateGraph

    graph = StateGraph(AgentState)

    graph.add_node("chat_agent", chat_agent)

    graph.set_entry_point("chat_agent")
    graph.add_edge("chat_agent", END)

    return graph.compile()


# Lazily compiled graphs (built on first use)
_search_graph = None
_chat_graph = None


def _get_search_graph():
    global _search_graph
    if _search_graph is None:
        _search_graph = build_search_graph()
    return _search_graph


def _get_chat_graph():
    global _chat_graph
    if _chat_graph is None:
        _chat_graph = build_chat_graph()
    return _chat_graph


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
    result = _get_search_graph().invoke(state)
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
    result = _get_chat_graph().invoke(state)
    return result.get("chat_reply", "")


def run_search_streaming(query: str, use_cbeta: bool = False,
                         on_chunk=None) -> dict:
    """Execute the search pipeline with streaming synthesis.

    Args:
        query: Search query
        use_cbeta: Whether to search CBETA
        on_chunk: Optional callback(chunk_text: str) for streaming synthesis

    Returns:
        dict with all_hits, synthesis, traditional_query
    """
    # Build initial state
    state = {
        "original_query": query,
        "traditional_query": "",
        "use_cbeta": use_cbeta,
        "local_hits": [],
        "cbeta_hits": [],
        "all_hits": [],
        "synthesis": "",
    }
    
    # Run query processor
    query_result = query_processor(state)  # type: ignore
    state.update(query_result)  # type: ignore
    
    # Run local and CBETA search in parallel
    local_result = local_searcher(state)  # type: ignore
    cbeta_result = cbeta_scraper_node(state)  # type: ignore
    state.update(local_result)  # type: ignore
    state.update(cbeta_result)  # type: ignore
    
    # Run streaming synthesizer
    synth_result = synthesizer_streaming(state, on_chunk=on_chunk)  # type: ignore
    state.update(synth_result)  # type: ignore
    
    return state  # type: ignore


def run_chat_streaming(message: str, history: list[dict],
                       session_id: int | None = None,
                       synthesis: str = "",
                       on_chunk=None) -> str:
    """Run a chat turn with streaming response.
    
    Args:
        message: User message
        history: Chat history
        session_id: Optional session ID for loading history from DB
        synthesis: Optional synthesis from search phase to include in context
        on_chunk: Optional callback(chunk_text: str) for streaming
    
    Returns:
        Complete assistant reply
    """
    import app.config as cfg

    if not cfg.settings.llm_provider_api_key:
        return "LLM 未配置，请在设置中添加 API Key。"

    if session_id is not None and not history:
        db_msgs = get_messages_by_session(session_id)
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in db_msgs
        ]
    
    # Get search context
    search_result = run_search(query=message, use_cbeta=False)
    local = list(search_result.get("local_hits", []))
    cbeta = list(search_result.get("cbeta_hits", []))
    
    for h in local:
        h.setdefault("source", "local")
    all_hits = local + cbeta
    
    excerpts = "\n".join(_format_excerpt(h) for h in _hits_for_llm_context(all_hits)[:20])

    # Build system prompt with synthesis context if available
    system_content = (
        "你是一位汉语言古籍研究助手。目前用户检索相应的词语文语料，得到了以下检索结果，"
        f"检索词：{search_result.get('traditional_query', '')}\n"
        f"检索结果：\n{excerpts}"
    )
    if synthesis:
        system_content += (
            "\n\n以下是 AI 对该词语的分析结果：\n"
            f"{synthesis}"
        )
    system_content += (
        "\n\n务必注意回答的专业性和准确性，并适当结合检索结果的例句和上述分析结果，"
        "以及联网搜索得到的相关资料，理解该词语在古籍中的出处和上下文含义，"
        "用户会基于上述的检索结果和分析报告，向你进行多轮对话，如果用户以正常聊天的方式与你对话，请直接对话即可，若用户提问与上述分析的结果相关的问题，请结合分析结果提供专业化的回答。"
    )
    
    try:
        client = _get_client()
        messages: list = [
            {"role": "system", "content": system_content}
        ]
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })
        messages.append({"role": "user", "content": message})
        
        extra_kwargs = _thinking_kwargs()
        stream = client.chat.completions.create(
            model=cfg.settings.llm_model_name,
            messages=messages,
            stream=True,
            **extra_kwargs,
        )
        
        reply = ""
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                reply += content
                if on_chunk:
                    on_chunk(content)
        
        return reply
    except Exception:
        logger.exception("Streaming chat failed")
        return "抱歉，处理请求时出错，请稍后再试。"
