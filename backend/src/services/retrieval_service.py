"""Retrieval engine of the search API: picks the strategy for a request and presents results.

The work itself lives in services/retrieval/: ``fusion`` (hybrid candidate search),
``planned_kis`` and ``trake`` (the multi-event strategies) and ``presenter`` (API models).
"""

from collections.abc import Callable

import numpy as np

from core.intro_exclusion import IntroExclusionPolicy
from infrastructure.blip2_reranker import BLIP2Reranker
from infrastructure.embedding_service import EmbeddingService
from models.errors import RetrievalDataError
from models.query import KISQueryPlan, QueryVariants
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from repositories.object_repository import KeyframeObjectRepository
from repositories.text_repository import KeyframeTextRepository
from repositories.traffic_repository import TrafficMetadataRepository, is_traffic_video
from repositories.vector_repository import KeyframeVectorRepository
from schemas.search import (
    KISSearchRequest,
    SearchRequest,
    SimilarSearchRequest,
    SimilarSearchResponse,
    SingleSearchResult,
    TrafficSearchRequest,
    TRAKESearchRequest,
    TRAKESearchResult,
)
from services.ports import EnhancedQueries, RetrievalOutcome
from services.retrieval.fusion import (
    AsrModality,
    CandidateSearch,
    ObjectModality,
    VisualModality,
)
from services.retrieval.planned_kis import PlannedKisSearch
from services.retrieval.presenter import ResultPresenter
from services.retrieval.similar import SimilarSearch
from services.retrieval.trake import TrakeConfig, TrakeSearch

__all__ = ["RetrievalDataError", "RetrievalService", "TrakeConfig"]

_TRAFFIC_UNAVAILABLE = "Traffic metadata is unavailable (data/traffic_camera/cameras.json)."
_NO_TRAFFIC_MATCH = "No traffic keyframe matches the selected filters."


class RetrievalService:
    """Implements services.ports.RetrievalEngine."""

    def __init__(
        self,
        *,
        keyframe_repository: KeyframeMetadataRepository,
        siglip_vector_repo: KeyframeVectorRepository,
        beit3_vector_repo: KeyframeVectorRepository,
        text_repository: KeyframeTextRepository,
        embedding_service: EmbeddingService,
        blip2_reranker: BLIP2Reranker | None = None,
        intro_exclusion_policy: IntroExclusionPolicy | None = None,
        object_repository: KeyframeObjectRepository | None = None,
        traffic_repository: TrafficMetadataRepository | None = None,
        fps_lookup: Callable[[str], float | None] | None = None,
        trake_config: TrakeConfig | None = None,
    ) -> None:
        intro_policy = intro_exclusion_policy or IntroExclusionPolicy()
        self._traffic_repository = traffic_repository
        self._candidates = CandidateSearch(
            visual=VisualModality(
                # Looked up per call: a model is only needed once a search chooses it.
                encoders={
                    "siglip": lambda text: embedding_service.get_siglip_embedding(text),
                    "beit3": lambda text: embedding_service.get_beit3_embedding(text),
                },
                indexes={"siglip": siglip_vector_repo, "beit3": beit3_vector_repo},
                intro_exclusion_policy=intro_policy,
            ),
            asr=AsrModality(text_repository, intro_policy),
            objects=ObjectModality(object_repository) if object_repository is not None else None,
            intro_exclusion_policy=intro_policy,
            reranker=blip2_reranker,
        )
        self._planned_kis = PlannedKisSearch(self._candidates)
        self._trake = TrakeSearch(
            self._candidates, trake_config or TrakeConfig(), fps_lookup, blip2_reranker
        )
        self._presenter = ResultPresenter(object_repository, traffic_repository)
        self._similar = SimilarSearch(
            keyframe_repository,
            {"siglip": siglip_vector_repo, "beit3": beit3_vector_repo},
            intro_policy,
        )

    def similar(self, request: SimilarSearchRequest) -> SimilarSearchResponse:
        """Keyframes that look like the given one (raises ExampleNotFound)."""

        def allowed_for(video_id: str) -> np.ndarray | None:
            if request.include_traffic or is_traffic_video(video_id):
                return None
            return self._non_traffic_mask()

        candidates = self._similar.search(
            request.video_id, request.frame_id, request.model_choices, request.top_k, allowed_for
        )
        return SimilarSearchResponse(
            query_type="SIMILAR",
            video_id=request.video_id,
            frame_id=request.frame_id,
            model_choices=list(request.model_choices),
            results=self._presenter.single(candidates),
        )

    def retrieve(
        self, request: SearchRequest, enhanced_queries: EnhancedQueries = None
    ) -> RetrievalOutcome:
        warnings: list[str] = []
        filtered_keyframes: int | None = None
        results: tuple[SingleSearchResult | TRAKESearchResult, ...]
        if isinstance(request, TRAKESearchRequest):
            trake_queries = enhanced_queries if isinstance(enhanced_queries, dict) else None
            # TRAKE is never asked about the traffic videos, so they are left out entirely.
            sequences = self._trake.search(
                request, trake_queries, self._non_traffic_mask(), warnings
            )
            results = self._presenter.trake(sequences)
        elif isinstance(request, KISSearchRequest) and isinstance(enhanced_queries, KISQueryPlan):
            allowed = None if request.include_traffic else self._non_traffic_mask()
            candidates = self._planned_kis.search(request, enhanced_queries, allowed, warnings)
            results = self._presenter.single(candidates)
        else:
            enhanced = enhanced_queries if isinstance(enhanced_queries, QueryVariants) else None
            allowed = None
            if isinstance(request, TrafficSearchRequest):
                allowed = self._traffic_mask(request)
                filtered_keyframes = int(allowed.sum())
                if filtered_keyframes == 0:
                    warnings.append(_NO_TRAFFIC_MATCH)
            elif isinstance(request, KISSearchRequest) and not request.include_traffic:
                allowed = self._non_traffic_mask()
            candidates = self._candidates.search(
                request.query,
                request.model_choices,
                request.top_k * 5,
                request.search_sources,
                enhanced,
                warnings,
                rerank=request.use_reranking,
                object_query=request.object_query,
                allowed=allowed,
            )
            results = self._presenter.single(candidates[: request.top_k])
        return RetrievalOutcome(
            results=results,
            warnings=tuple(dict.fromkeys(warnings)),
            filtered_keyframes=filtered_keyframes,
        )

    def _traffic_mask(self, request: TrafficSearchRequest) -> np.ndarray:
        if self._traffic_repository is None or not self._traffic_repository.available:
            raise RetrievalDataError(_TRAFFIC_UNAVAILABLE)
        return self._traffic_repository.allowed_mask(request.filters)

    def _non_traffic_mask(self) -> np.ndarray | None:
        """Keyframes outside the traffic videos, or None (no restriction) without traffic data."""
        if self._traffic_repository is None or not self._traffic_repository.available:
            return None
        return self._traffic_repository.non_traffic_mask()
