"""LangGraph multi-agent workflow for classical text search and analysis."""

import json
import logging
import operator
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, TypedDict

from app.core.database import search_content, get_messages_by_session, get_setting

logger = logging.getLogger(__name__)
_JUDGE_MAX_WORKERS = 8
_DEFAULT_SYNTHESIS_USER_PROMPT = (
    "请从汉语词汇史的角度，结合汉译佛典和本土文献语料，"
    "梳理并分析用户所检索词语的中土化路径。"
)


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
            include_commentary = _include_commentary_in_synthesis_prompt()
            excerpts = "\n".join(
                _format_excerpt(h)
                for h in _hits_for_llm_context(
                    all_hits,
                    include_commentary_local=include_commentary,
                )[:20]
            )
            messages: list = [
                {"role": "system", "content": (
                    "你是一位汉语言古籍研究助手。目前用户检索相应的词语文语料，得到了以下检索结果，"
                    f"检索词：{state.get('traditional_query', '')}\n"
                    f"检索结果：\n{excerpts}"
                    "\n\n务必注意回答的专业性和准确性，并适当结合检索结果的例句，以及联网搜索得到的相关资料，理解该词语在古籍中的出处和上下文含义，根据用户的输入，为用户提供专业化的分析。"
                )},
                {"role": "user", "content": (
                    _synthesis_user_prompt()
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
    include_commentary = _include_commentary_in_synthesis_prompt()
    excerpts = "\n".join(
        _format_excerpt(h)
        for h in _hits_for_llm_context(
            all_hits,
            include_commentary_local=include_commentary,
        )[:20]
    )
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
        label = h.get("content_label") or ("正文" if h.get("is_original_text", False) else "注文")
        dynasty = h.get("dynasty", "") or "朝代未详"
        category = h.get("category", "") or "来源未详"
        tag = f"[local/{label}/{dynasty}/{category}]"
    else:
        tag = f"[{source}]"
    return f"- {tag} {h.get('filename', '')}: {h.get('snippet', '')}"


def _hits_for_llm_context(
    hits: list[dict],
    include_commentary_local: bool = False,
) -> list[dict]:
    """Filter hits for LLM prompt with optional local 注文 inclusion."""

    def _keep(hit: dict) -> bool:
        if hit.get("source") != "local":
            return True
        if hit.get("is_original_text", False):
            return True
        if include_commentary_local and hit.get("content_label") == "注文":
            return True
        return False

    return [
        h for h in hits
        if _keep(h)
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


def _judge_search_extra_body() -> dict:
    """Build extra_body for forced web-search judgement requests."""
    search_options: dict = {
        "forced_search": True,
        # Prefer recall-oriented strategy for正文/注文 judgement.
        "search_strategy": "max",
    }

    return {
        "enable_search": True,
        "enable_thinking": False,
        "search_options": search_options,
    }


def _judge_completion_with_forced_search(
    client,
    model: str,
    messages: list[dict],
    stage: str = "",
):
    """Call Chat Completions with forced web search."""
    extra_body = _judge_search_extra_body()
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "[judge%s] request model=%s extra_body=%s messages=%s",
            f":{stage}" if stage else "",
            model,
            json.dumps(extra_body, ensure_ascii=False),
            json.dumps(messages, ensure_ascii=False),
        )

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        extra_body=extra_body,
    )
    if logger.isEnabledFor(logging.DEBUG):
        content = ""
        try:
            content = resp.choices[0].message.content or ""
        except Exception:
            content = ""
        logger.debug(
            "[judge%s] response_message=%s",
            f":{stage}" if stage else "",
            content,
        )
    return resp


def _book_title_from_filename(filename: str) -> str:
    """Extract book title from 《...》 in filename; fallback to basename without .pdf."""
    name = (filename or "").strip()
    if not name:
        return ""
    m = re.search(r"《([^》]+)》", name)
    if m:
        return m.group(1).strip()
    return name[:-4] if name.lower().endswith(".pdf") else name


def _source_hint_from_hit(h: dict) -> str:
    """Build source hint with only the extracted book title."""
    filename = str(h.get("filename", "")).strip()
    title = _book_title_from_filename(filename)
    return f"文献名：{title}" if title else "文献名：未知"


def _parse_judge_result(data: dict) -> tuple[str, int, str]:
    """Parse model JSON into (verdict, confidence, reason)."""
    raw_verdict = str(data.get("verdict", "")).strip()
    raw_conf = data.get("confidence", 50)
    reason = str(data.get("reason", "")).strip()

    if raw_verdict in {"正文", "原文", "原始正文"}:
        verdict = "正文"
    elif raw_verdict in {"注文", "注释", "註文", "注文/注释"}:
        verdict = "注文"
    else:
        raw_flag = data.get("is_original_text")
        if isinstance(raw_flag, bool):
            verdict = "正文" if raw_flag else "注文"
        else:
            flag = str(raw_flag).strip().lower()
            if flag in {"true", "1", "yes", "是"}:
                verdict = "正文"
            elif flag in {"false", "0", "no", "否", "注", "注文"}:
                verdict = "注文"
            else:
                # Strict binary classification fallback.
                verdict = "正文"

    try:
        confidence = int(raw_conf)
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))
    return verdict, confidence, reason


def _judge_sentence_is_original_text(
    sentence: str,
    query: str,
    source_hint: str = "",
) -> tuple[bool, str]:
    """Use web-search LLM with two-pass verification for 正文/注文 judgement."""
    logger.info(
        "Judge start | query=%s | source_hint=%s | sentence=%s",
        query,
        source_hint or "文献信息缺失",
        sentence,
    )
    client = _get_client()
    model = _web_search_model()
    prompt_source = source_hint or "文献信息缺失"
    title_part = ""
    if source_hint and "文献名：" in source_hint:
        title_part = source_hint.split("；", 1)[0].replace("文献名：", "").strip()
    search_task_1 = f"{title_part} {sentence} 原文".strip() if title_part else f"{sentence} 原文"
    search_task_2 = f"{title_part} {query} {sentence} 原文".strip() if title_part else f"{query} {sentence} 原文"
    normalized_sentence = re.sub(r"[「」『』【】《》“”\"'：:，,。！？!?；;（）()\\s]", "", sentence)
    normalized_for_search = normalized_sentence or sentence
    search_task_3 = f"{title_part} {normalized_for_search} 原文".strip() if title_part else f"{normalized_for_search} 原文"
    search_task_4 = f"{title_part} {query} {normalized_for_search} 原文".strip() if title_part else f"{query} {normalized_for_search} 原文"
    short_fragment = normalized_for_search[:22] if normalized_for_search else sentence[:22]
    search_task_5 = (
        f"{title_part} {query} {short_fragment} 原文".strip()
        if title_part
        else f"{query} {short_fragment} 原文"
    )

    messages_round_1 = [
        {
            "role": "system",
            "content": (
                "你是古籍正文判定助手。你必须联网检索。"
                "你必须严格二分类，只能输出“正文”或“注文”。"
                "注意：句中出现“云”“记云”“曰”等引文表达，不能单独作为“注文”证据；"
                "传记正文本身常包含引文与考据语句。"
                "只有出现明确注释层级证据（如注、疏、音义、夹注、校勘记）时，才可判“注文”。"
                "若证据不足，优先判“正文”。"
                "仅返回 JSON："
                "{\"verdict\":\"正文|注文\",\"confidence\":0-100,\"reason\":\"简短理由\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"检索词：{query}\n"
                f"文献信息：{prompt_source}\n"
                f"待判定句子：{sentence}\n"
                "请至少执行三次检索（第一轮需带书名）：\n"
                f"1) {search_task_1}\n"
                f"2) {search_task_2}\n"
                f"3) {search_task_5}\n"
                "不得仅凭语气、文风或是否引述他书来判断，必须基于检索到的文本结构证据。"
                "判断该句更可能属于古籍原始正文，还是注文/注释/后人案语。"
            ),
        },
    ]
    resp_round_1 = _judge_completion_with_forced_search(
        client, model, messages_round_1, stage="round1"
    )
    data_1 = _extract_json_object(resp_round_1.choices[0].message.content or "")
    verdict_1, conf_1, reason_1 = _parse_judge_result(data_1)

    # High-confidence first-pass positive result can be used directly.
    # Negative verdict always requires round-2 confirmation.
    if verdict_1 == "正文" and conf_1 >= 70:
        return True, f"R1正文({conf_1}) {reason_1}"

    # Second pass: explicit re-check, especially when pass-1 is negative/uncertain.
    messages_round_2 = [
        {
            "role": "system",
            "content": (
                "你是古籍正文复核助手。你必须联网检索。"
                "你必须严格二分类，只能输出“正文”或“注文”。"
                "复核原则：只有证据明确指向注文/注释时，才判“注文”。"
                "注意：仅凭“某某云”“按”等表达不能判注文；"
                "若无明确注释层级证据，应判“正文”。"
                "仅返回 JSON："
                "{\"verdict\":\"正文|注文\",\"confidence\":0-100,\"reason\":\"简短理由\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"检索词：{query}\n"
                f"文献信息：{prompt_source}\n"
                f"待判定句子：{sentence}\n"
                f"初判结果：{verdict_1}（置信度 {conf_1}）\n"
                "请再检索并复核（第二轮需去掉「」等符号后再检索，至少两次）：\n"
                f"1) {search_task_3}\n"
                f"2) {search_task_4}\n"
                "若仍无法命中，再尝试异体字写法。"
                "给出最终复核判断。"
            ),
        },
    ]
    resp_round_2 = _judge_completion_with_forced_search(
        client, model, messages_round_2, stage="round2"
    )
    data_2 = _extract_json_object(resp_round_2.choices[0].message.content or "")
    verdict_2, conf_2, reason_2 = _parse_judge_result(data_2)

    # Decision fusion: prioritize recall of 正文 while keeping strong negative checks.
    if verdict_2 == "正文" and conf_2 >= 55:
        result = (True, f"R1={verdict_1}({conf_1})；R2正文({conf_2}) {reason_2}")
        logger.info("Judge final | is_original=%s | reason=%s", result[0], result[1])
        return result
    if verdict_1 == "正文" and conf_1 >= 55:
        result = (True, f"R1正文({conf_1}) {reason_1}；R2={verdict_2}({conf_2})")
        logger.info("Judge final | is_original=%s | reason=%s", result[0], result[1])
        return result
    if verdict_1 == "注文" and verdict_2 == "注文" and min(conf_1, conf_2) >= 85:
        result = (False, f"R1注文({conf_1}) {reason_1}；R2注文({conf_2}) {reason_2}")
        logger.info("Judge final | is_original=%s | reason=%s", result[0], result[1])
        return result

    # Default to 正文 to avoid false negatives when evidence is weak.
    fallback_reason = (
        f"复核证据偏弱，默认正文。R1={verdict_1}({conf_1}) {reason_1}；"
        f"R2={verdict_2}({conf_2}) {reason_2}"
    )
    result = (True, fallback_reason)
    logger.info("Judge final | is_original=%s | reason=%s", result[0], result[1])
    return result


def _annotate_local_hits_with_web_search(hits: list[dict], query: str) -> list[dict]:
    """Classify local hits as 正文/非正文 with parallel web-search judgement."""
    if not hits:
        return []

    sentence_cache: dict[tuple[str, str], tuple[bool, str]] = {}
    unique_items: list[tuple[str, str]] = []
    for h in hits:
        sentence = str(h.get("keyword_sentence") or h.get("snippet") or "").strip()
        source_hint = _source_hint_from_hit(h)
        cache_key = (sentence, source_hint)
        if not sentence:
            h["is_original_text"] = False
            h["content_label"] = "注文"
            continue
        if cache_key not in sentence_cache:
            sentence_cache[cache_key] = (False, "")
            unique_items.append(cache_key)

    if unique_items:
        num_workers = min(_JUDGE_MAX_WORKERS, len(unique_items))
        logger.info(
            "Parallel正文判定: %d items, %d threads",
            len(unique_items),
            num_workers,
        )
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            future_to_key = {
                pool.submit(
                    _judge_sentence_is_original_text,
                    sentence,
                    query,
                    source_hint,
                ): (sentence, source_hint)
                for sentence, source_hint in unique_items
            }
            for future in as_completed(future_to_key):
                cache_key = future_to_key[future]
                try:
                    sentence_cache[cache_key] = future.result()
                except Exception:
                    logger.exception("Web-search sentence judgement failed")
                    sentence_cache[cache_key] = (False, "")

    for h in hits:
        sentence = str(h.get("keyword_sentence") or h.get("snippet") or "").strip()
        if not sentence:
            continue
        source_hint = _source_hint_from_hit(h)
        is_original, reason = sentence_cache.get((sentence, source_hint), (False, ""))
        h["is_original_text"] = is_original
        h["content_label"] = "正文" if is_original else "注文"
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


def _include_commentary_in_synthesis_prompt() -> bool:
    """Whether to include local 注文 hits in synthesis prompt context."""
    return get_setting("include_commentary_in_synthesis_prompt") == "true"


def _synthesis_user_prompt() -> str:
    """Return configurable synthesis user prompt with a safe default."""
    prompt = get_setting("synthesis_user_prompt") or _DEFAULT_SYNTHESIS_USER_PROMPT
    return prompt if prompt.endswith("\n") else f"{prompt}\n"


def build_chat_graph():
    """Build and compile the chat workflow graph."""
    from langgraph.graph import END, StateGraph

    graph = StateGraph(AgentState)

    graph.add_node("chat_agent", chat_agent)

    graph.set_entry_point("chat_agent")
    graph.add_edge("chat_agent", END)

    return graph.compile()


# Lazily compiled graphs (built on first use)
_chat_graph = None


def _get_chat_graph():
    global _chat_graph
    if _chat_graph is None:
        _chat_graph = build_chat_graph()
    return _chat_graph


# ── Public API ───────────────────────────────────────────────────────────────

def run_search(
    query: str,
    use_cbeta: bool = False,
    on_chunk=None,
) -> dict:
    """Execute the search pipeline (optionally with streaming synthesis chunks).

    Args:
        query: Search query.
        use_cbeta: Whether to search CBETA.
        on_chunk: Optional callback(chunk_text: str) for synthesis streaming.

    Returns:
        dict with all_hits, synthesis, traditional_query.
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
    with ThreadPoolExecutor(max_workers=2) as pool:
        local_future = pool.submit(local_searcher, state)  # type: ignore
        cbeta_future = pool.submit(cbeta_scraper_node, state)  # type: ignore
        local_result = local_future.result()
        cbeta_result = cbeta_future.result()

    state.update(local_result)  # type: ignore
    state.update(cbeta_result)  # type: ignore

    # Run streaming synthesizer
    synth_result = synthesizer_streaming(state, on_chunk=on_chunk)  # type: ignore
    state.update(synth_result)  # type: ignore

    return state  # type: ignore


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
