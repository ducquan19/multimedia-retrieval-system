from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    max_trake_events: int = 10
    max_query_length: int = Field(default=2_000, ge=1)
    max_answer_length: int = Field(default=2_000, ge=1)

    gemini_api_key: str | None = None
    keyframes_filename: str = "keyframes.json"
    video_sources_filename: str = "video_sources.json"

    # Private Hugging Face dataset for videos that cannot be public (read-only token)
    hf_token: SecretStr | None = None
    hf_private_repo: str = "dwctien/aic26-videos-private"
    hf_signed_url_ttl_seconds: int = Field(default=2_700, ge=60)

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
        if self.max_trake_events < 1:
            raise ValueError("max_trake_events must be at least 1")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
