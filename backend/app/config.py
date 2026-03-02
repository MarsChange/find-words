"""Application configuration management."""

import os
import json
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


class Settings(BaseSettings):
    """Global application settings."""

    app_name: str = "古籍词语检索分析系统"
    debug: bool = False

    # Database
    db_path: str = str(
        Path(__file__).resolve().parent.parent / "data" / "findwords.db"
    )

    # Upload directory
    upload_dir: str = str(
        Path(__file__).resolve().parent.parent / "data" / "uploads"
    )

    # LLM provider
    llm_provider: str = "DeepSeek"
    llm_provider_base_url: str = "https://api.deepseek.com/v1"
    llm_provider_api_key: str = ""
    llm_model_name: str = "deepseek-reasoner"

    # Selenium
    chrome_driver_path: str = ""
    headless: bool = True

    # Search defaults
    snippet_context_chars: int = 50

    model_config = {"env_prefix": "FINDWORDS_"}


def load_settings() -> Settings:
    """Load settings from config.json, falling back to env vars / defaults."""
    overrides: dict = {}
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                overrides = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return Settings(**overrides)


def save_settings(updates: dict) -> Settings:
    """Persist setting changes to config.json and return new settings."""
    current: dict = {}
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                current = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    current.update(updates)
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return load_settings()


settings = load_settings()
