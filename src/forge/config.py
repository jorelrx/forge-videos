from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FORGE_", env_file=".env", extra="ignore", populate_by_name=True
    )

    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FORGE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    model: str = "claude-opus-4-8"
    effort: str = "high"
    output_dir: Path = Path("output/roteiros")
    log_level: str = "INFO"
    max_review_rounds: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
