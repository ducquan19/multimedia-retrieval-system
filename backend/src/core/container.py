"""Construction of the long-lived services (models, indexes, repositories).

``build_services`` is what the API runs at startup; tests pass their own factory to
``create_app`` so they never load the real models or the multi-gigabyte indexes.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from core.config import Settings
from core.intro_exclusion import IntroExclusionPolicy
from infrastructure.embedding_service import EmbeddingService
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from repositories.object_repository import KeyframeObjectRepository
from repositories.text_repository import KeyframeTextRepository
from repositories.traffic_repository import TrafficMetadataRepository
from services.search_service import SearchService
from services.video_source_service import VideoSourceService

logger = logging.getLogger(__name__)


@dataclass
class AppServices:
    search_service: SearchService
    keyframe_repository: KeyframeMetadataRepository
    object_repository: KeyframeObjectRepository
    traffic_repository: TrafficMetadataRepository
    # name -> zero-argument check returning (ok, detail), reported by /api/health/ready
    readiness_checks: dict[str, Callable[[], tuple[bool, str]]] = field(default_factory=dict)
    closers: list[Callable[[], None]] = field(default_factory=list)

    def close(self) -> None:
        for close in reversed(self.closers):
            try:
                close()
            except Exception:  # noqa: BLE001 - shutdown must continue
                logger.exception("Error while closing a service")


ServicesFactory = Callable[[Settings, VideoSourceService], AppServices]


def elasticsearch_check(text_repository: KeyframeTextRepository, es_url: str) -> tuple[bool, str]:
    if not text_repository.ping():
        return False, f"unreachable: {es_url}"
    status, detail = text_repository.index_order_status()
    return status == "ok", detail


def build_services(settings: Settings, video_sources: VideoSourceService) -> AppServices:
    # Imported here so that importing the app (e.g. for tests) does not import torch models.
    from infrastructure.blip2_reranker import BLIP2Reranker
    from infrastructure.query_enhancer import GeminiQueryEnhancer
    from repositories.vector_repository import KeyframeVectorRepository
    from services.retrieval_service import RetrievalService, TrakeConfig

    logger.debug("Loading keyframe metadata from %s", settings.data_root)
    keyframe_repository = KeyframeMetadataRepository(
        settings.data_root,
        settings.keyframes_filename,
        asr_texts_filename=settings.asr_texts_filename,
    )
    keyframe_repository.load()
    intro_policy = IntroExclusionPolicy(settings.intro_frame_counts)

    siglip_repo = KeyframeVectorRepository(
        "SigLIP", settings.faiss_siglip_path, settings.siglip_dim, keyframe_repository, intro_policy
    )
    beit3_repo = KeyframeVectorRepository(
        "BEiT-3", settings.faiss_beit3_path, settings.beit3_dim, keyframe_repository, intro_policy
    )
    embedding_service = EmbeddingService(
        settings.siglip_model_id,
        settings.beit3_checkpoint_dir,
        settings.device,
        siglip_revision=settings.siglip_model_revision,
    )
    text_repository = KeyframeTextRepository(
        settings.es_url, keyframe_repository, intro_policy, settings.es_index_name
    )
    object_repository = KeyframeObjectRepository(
        settings.object_index_path, keyframe_repository, intro_policy
    )
    object_repository.load()
    traffic_repository = TrafficMetadataRepository(settings.data_root, keyframe_repository)
    if traffic_repository.available:
        traffic_repository.warm_up()

    reranker = BLIP2Reranker(
        settings.data_root,
        settings.enable_reranking,
        model_id=settings.blip2_model_id,
        revision=settings.blip2_model_revision or None,
        device=settings.device,
        depth=settings.rerank_depth,
    )
    retrieval_service = RetrievalService(
        keyframe_repository=keyframe_repository,
        siglip_vector_repo=siglip_repo,
        beit3_vector_repo=beit3_repo,
        text_repository=text_repository,
        embedding_service=embedding_service,
        blip2_reranker=reranker,
        intro_exclusion_policy=intro_policy,
        object_repository=object_repository,
        traffic_repository=traffic_repository,
        fps_lookup=video_sources.fps,
        trake_config=TrakeConfig(
            max_gap_seconds=settings.trake_max_gap_seconds,
            decay_per_second=settings.trake_decay_per_second,
            dedup_seconds=settings.trake_dedup_seconds,
        ),
    )
    query_enhancer = GeminiQueryEnhancer(
        api_key=settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None,
        object_labels=object_repository.labels(),
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
    )
    search_service = SearchService(
        retrieval_engine=retrieval_service,
        query_enhancer=query_enhancer,
        max_trake_events=settings.max_trake_events,
        max_query_length=settings.max_query_length,
        object_repository=object_repository,
    )

    def model_check(model, error: str | None, index: KeyframeVectorRepository):
        def check() -> tuple[bool, str]:
            if model is None:
                return False, f"model not loaded: {error}"
            if not index.available:
                return False, f"index missing: {index.index_path}"
            return True, "ok"

        return check

    return AppServices(
        search_service=search_service,
        keyframe_repository=keyframe_repository,
        object_repository=object_repository,
        traffic_repository=traffic_repository,
        readiness_checks={
            "siglip": model_check(
                embedding_service.siglip_model, embedding_service.siglip_error, siglip_repo
            ),
            "beit3": model_check(
                embedding_service.beit3_model, embedding_service.beit3_error, beit3_repo
            ),
            "elasticsearch": lambda: elasticsearch_check(text_repository, settings.es_url),
            "objects": lambda: (
                (True, "ok") if object_repository.available else (False, "object index missing")
            ),
            "gemini": lambda: (
                (True, f"ok, {query_enhancer.usage_summary()}")
                if query_enhancer.available
                else (False, "no API key or client")
            ),
        },
        closers=[text_repository.close],
    )
