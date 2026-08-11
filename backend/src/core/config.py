from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.constants import TOP_K_OPTIONS


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
    max_query_length: int = Field(default=2_000, ge=1)
    max_answer_length: int = Field(default=2_000, ge=1)
    retrieval_mode: str = "hybrid"
    gemini_mode: str = "mock"
    keyframes_filename: str = "keyframes.json"

    # Hybrid Retrieval settings
    faiss_siglip_filename: str = "indexing/siglip.index"
    faiss_beit3_filename: str = "indexing/beit3.index"
    sqlite_db_filename: str = "metadata.db"
    es_url: str = "http://localhost:9200"
    enable_reranking: bool = False

    @property
    def faiss_siglip_path(self) -> Path:
        return self.data_root / self.faiss_siglip_filename

    @property
    def faiss_beit3_path(self) -> Path:
        return self.data_root / self.faiss_beit3_filename

    @property
    def sqlite_db_path(self) -> Path:
        return self.data_root / self.sqlite_db_filename

    @model_validator(mode="after")
    def validate_public_config(self) -> "Settings":
        if self.default_top_k not in TOP_K_OPTIONS:
            raise ValueError(f"default_top_k must be one of {TOP_K_OPTIONS}")
        if self.max_trake_events < 1:
            raise ValueError("max_trake_events must be at least 1")
        if self.retrieval_mode not in ["hybrid", "siglip", "beit3"]:
            raise ValueError("retrieval_mode must be 'hybrid', 'siglip', or 'beit3'")
        if self.gemini_mode not in ["mock", "gemini"]:
            raise ValueError("gemini_mode must be 'mock' or 'gemini'")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
