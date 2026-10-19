from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.intro_exclusion import DEFAULT_INTRO_FRAME_COUNTS


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
    frontend_origin: AnyHttpUrl = AnyHttpUrl("http://localhost:5173")
    # The API has no authentication and submits to DRES with the team account, so by default it
    # answers only requests from this machine. True shares it on the network: do it knowingly.
    allow_remote_clients: bool = False
    max_trake_events: int = Field(default=10, ge=1)
    max_query_length: int = Field(default=2_000, ge=1)
    max_answer_length: int = Field(default=2_000, ge=1)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_dir: Path | None = Path("logs")

    # Only these top-level folders of data_root are served under /media. Everything else in
    # data_root (indexes, metadata, the DRES submission log) is never exposed over HTTP.
    media_dirs: tuple[str, ...] = ("keyframes", "traffic_keyframes", "videos")

    keyframes_filename: str = "keyframes.json"
    video_sources_filename: str = "video_sources.json"
    object_index_filename: str = "objects_index.json"
    # Shot transcripts written by scripts/build_es_index.py, shown next to each keyframe
    asr_texts_filename: str = "asr_texts.json"

    # Private Hugging Face dataset for videos that cannot be public (read-only token)
    hf_token: SecretStr | None = None
    hf_private_repo: str = "dwctien/aic26-videos-private"
    hf_signed_url_ttl_seconds: int = Field(default=2_700, ge=60)

    # Models (device: "cuda", "cpu" or empty for automatic)
    device: str | None = None
    siglip_model_id: str = "google/siglip2-so400m-patch14-384"
    # Hub commit of the model. Query embeddings must come from the same weights and processor
    # as the indexed keyframe embeddings, so this stays equal to SIGLIP2_REVISION in
    # scripts/embed_keyframes.py (a test checks it). Empty = latest "main" (not recommended).
    siglip_model_revision: str | None = "e8e487298228002f3d8a82e0cd5c8ea9c567f57f"
    siglip_dim: int = Field(default=1152, ge=1)
    beit3_checkpoint_dirname: str = "checkpoint"
    beit3_dim: int = Field(default=768, ge=1)

    # Vector indexes (relative to data_root)
    faiss_siglip_filename: str = "indexing/siglip.index"
    faiss_beit3_filename: str = "indexing/beit3.index"

    # Elasticsearch (ASR BM25)
    es_url: str = "http://localhost:9200"
    es_index_name: str = "keyframes_metadata"

    # Gemini query enhancement / KIS planning
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    # Gemini runs inside the search request; past this the search goes on with the raw query.
    gemini_timeout_seconds: float = Field(default=10.0, gt=0)

    # BLIP-2 reranking
    enable_reranking: bool = False
    blip2_model_id: str = "Salesforce/blip2-itm-vit-g"
    blip2_model_revision: str | None = "520bf73fd0ef6ccce791cd3f06908040aef2d8cc"
    rerank_depth: int = Field(default=100, ge=1)

    # Opening intro frames excluded from every search, per programme group (video id prefix)
    intro_frame_counts: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_INTRO_FRAME_COUNTS)
    )

    # TRAKE temporal constraints (seconds of video time between consecutive events)
    trake_max_gap_seconds: float = Field(default=120.0, gt=0)
    trake_decay_per_second: float = Field(default=0.010, ge=0)
    # Sequences whose every event shows the same moment (same shot, or within this many seconds)
    # count as one candidate; only the best is kept. 0 disables the merge.
    trake_dedup_seconds: float = Field(default=2.0, ge=0)

    # DRES submission (credentials only live in .env; the browser never sees them)
    dres_base_url: str = "https://eventretrieval.one"
    dres_username: str | None = None
    dres_password: SecretStr | None = None
    dres_log_filename: str = "dres_submissions.jsonl"

    @field_validator("media_dirs")
    @classmethod
    def validate_media_dirs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if not name or "/" in name or "\\" in name or name in {".", ".."}:
                raise ValueError(f"media_dirs entries must be plain folder names, got {name!r}")
        return value

    @property
    def faiss_siglip_path(self) -> Path:
        return self.data_root / self.faiss_siglip_filename

    @property
    def faiss_beit3_path(self) -> Path:
        return self.data_root / self.faiss_beit3_filename

    @property
    def object_index_path(self) -> Path:
        return self.data_root / self.object_index_filename

    @property
    def beit3_checkpoint_dir(self) -> Path:
        return self.data_root / self.beit3_checkpoint_dirname

    @property
    def dres_log_path(self) -> Path:
        return self.data_root / self.dres_log_filename


@lru_cache
def get_settings() -> Settings:
    return Settings()
