from functools import lru_cache
import logging
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from forge.logging import get_logger

logger = get_logger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FORGE_", env_file=".env", extra="ignore", populate_by_name=True
    )

    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FORGE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FORGE_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    model: str = "claude-opus-4-8"
    effort: str = "high"
    output_dir: Path = Path("output/roteiros")
    log_level: str = "INFO"
    max_review_rounds: int = 8

    provider: Literal["anthropic", "lm-studio", "openai"] = "anthropic"
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_model: str = "qwen/qwen3.5-9b"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    logger.info("Settings loaded", model=settings.model, provider=settings.provider, log_level=settings.log_level)
    return settings
