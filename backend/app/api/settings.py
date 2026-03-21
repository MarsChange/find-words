"""LLM and application settings API endpoints."""

from fastapi import APIRouter

from app.config import save_settings, load_settings
from app.core.database import get_setting, set_setting
from app.models.schemas import (
    AppSettingsResponse,
    AppSettingsUpdateRequest,
    LLMSettingsRequest,
    LLMSettingsResponse,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])
_DEFAULT_SYNTHESIS_USER_PROMPT = (
    "请从汉语词汇史的角度，结合汉译佛典和本土文献语料，"
    "梳理并分析用户所检索词语的中土化路径。"
)


@router.get("", response_model=LLMSettingsResponse)
async def get_settings() -> LLMSettingsResponse:
    """Return current LLM configuration (API key is masked)."""
    current = load_settings()
    return LLMSettingsResponse(
        llm_provider=current.llm_provider,
        llm_provider_base_url=current.llm_provider_base_url,
        llm_model_name=current.llm_model_name,
        has_api_key=bool(current.llm_provider_api_key),
    )


@router.put("", response_model=LLMSettingsResponse)
async def update_settings(req: LLMSettingsRequest) -> LLMSettingsResponse:
    """Update LLM provider settings."""
    updates = req.model_dump(exclude_none=True)
    new_settings = save_settings(updates)
    # Reload into the global settings object
    import app.config as cfg
    cfg.settings = new_settings

    return LLMSettingsResponse(
        llm_provider=new_settings.llm_provider,
        llm_provider_base_url=new_settings.llm_provider_base_url,
        llm_model_name=new_settings.llm_model_name,
        has_api_key=bool(new_settings.llm_provider_api_key),
    )


# ── Application settings (stored in DB) ──────────────────────────────────────

@router.get("/app", response_model=AppSettingsResponse)
async def get_app_settings() -> AppSettingsResponse:
    """Return application-level settings (CBETA max results, OCR model, etc.)."""
    val = get_setting("cbeta_max_results")
    cbeta_max = int(val) if val else 20
    thinking_val = get_setting("enable_thinking")
    enable_thinking = thinking_val == "true"
    ocr_model = get_setting("ocr_model") or "qwen3.5-plus"
    include_commentary_val = get_setting("include_commentary_in_synthesis_prompt")
    include_commentary_in_synthesis_prompt = include_commentary_val == "true"
    synthesis_user_prompt = (
        get_setting("synthesis_user_prompt")
        or _DEFAULT_SYNTHESIS_USER_PROMPT
    )
    return AppSettingsResponse(
        cbeta_max_results=cbeta_max,
        enable_thinking=enable_thinking,
        ocr_model=ocr_model,
        include_commentary_in_synthesis_prompt=include_commentary_in_synthesis_prompt,
        synthesis_user_prompt=synthesis_user_prompt,
    )


@router.patch("/app", response_model=AppSettingsResponse)
async def update_app_settings(req: AppSettingsUpdateRequest) -> AppSettingsResponse:
    """Update application-level settings."""
    if req.cbeta_max_results is not None:
        set_setting("cbeta_max_results", str(req.cbeta_max_results))
    if req.enable_thinking is not None:
        set_setting("enable_thinking", "true" if req.enable_thinking else "false")
    if req.ocr_model is not None:
        set_setting("ocr_model", req.ocr_model)
    if req.include_commentary_in_synthesis_prompt is not None:
        set_setting(
            "include_commentary_in_synthesis_prompt",
            "true" if req.include_commentary_in_synthesis_prompt else "false",
        )
    if req.synthesis_user_prompt is not None:
        prompt = req.synthesis_user_prompt
        if not prompt.strip():
            prompt = _DEFAULT_SYNTHESIS_USER_PROMPT
        set_setting("synthesis_user_prompt", prompt)
    val = get_setting("cbeta_max_results")
    cbeta_max = int(val) if val else 20
    thinking_val = get_setting("enable_thinking")
    enable_thinking = thinking_val == "true"
    ocr_model = get_setting("ocr_model") or "qwen3.5-plus"
    include_commentary_val = get_setting("include_commentary_in_synthesis_prompt")
    include_commentary_in_synthesis_prompt = include_commentary_val == "true"
    synthesis_user_prompt = (
        get_setting("synthesis_user_prompt")
        or _DEFAULT_SYNTHESIS_USER_PROMPT
    )
    return AppSettingsResponse(
        cbeta_max_results=cbeta_max,
        enable_thinking=enable_thinking,
        ocr_model=ocr_model,
        include_commentary_in_synthesis_prompt=include_commentary_in_synthesis_prompt,
        synthesis_user_prompt=synthesis_user_prompt,
    )
