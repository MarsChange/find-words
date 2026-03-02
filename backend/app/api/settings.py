"""LLM settings API endpoints."""

from fastapi import APIRouter

from app.config import save_settings, settings, load_settings
from app.models.schemas import LLMSettingsRequest, LLMSettingsResponse

router = APIRouter(prefix="/api/settings", tags=["settings"])


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
