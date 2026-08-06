from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aic_app.constants import TOP_K_OPTIONS


class Settings(BaseSettings):
    """Runtime settings loaded from AIC_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AIC_",
        extra="ignore",
    )

    app_name: str = "AIC 2026 Retrieval Inspector API"
    data_root: Path = Path("./data")
    frontend_origin: AnyHttpUrl = "http://localhost:5173"
    default_top_k: int = 20
    max_trake_events: int = 10
    max_query_length: int = Field(default=4_000, ge=1)
    max_answer_length: int = Field(default=4_000, ge=1)
    retrieval_mode: str = "mock"
    gemini_mode: str = "mock"
    manifest_filename: str = "manifest.json"
    fixture_filename: str = "fixtures/search_results.json"

    @model_validator(mode="after")
    def validate_public_config(self) -> "Settings":
        if self.default_top_k not in TOP_K_OPTIONS:
            raise ValueError(f"default_top_k must be one of {TOP_K_OPTIONS}")
        if self.max_trake_events < 1:
            raise ValueError("max_trake_events must be at least 1")
        if self.retrieval_mode != "mock" or self.gemini_mode != "mock":
            raise ValueError("MVP only supports mock retrieval and Gemini modes")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
