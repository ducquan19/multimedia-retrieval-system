from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TOP_K_OPTIONS = (10, 20, 50, 100)


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
    top_k_options: tuple[int, ...] = TOP_K_OPTIONS
    default_top_k: int = 20
    max_trake_events: int = 10
    retrieval_mode: str = "mock"
    gemini_mode: str = "mock"
    manifest_filename: str = "manifest.json"
    fixture_filename: str = "fixtures/search_results.json"

    @model_validator(mode="after")
    def validate_public_config(self) -> "Settings":
        if self.default_top_k not in self.top_k_options:
            raise ValueError("default_top_k must be one of top_k_options")
        if self.max_trake_events < 1:
            raise ValueError("max_trake_events must be at least 1")
        if self.retrieval_mode != "mock" or self.gemini_mode != "mock":
            raise ValueError("MVP only supports mock retrieval and Gemini modes")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
