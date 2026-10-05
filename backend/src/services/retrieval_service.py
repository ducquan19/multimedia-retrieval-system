import logging
import math
import uuid
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from core.intro_exclusion import IntroExclusionPolicy
from infrastructure.blip2_reranker import BLIP2Reranker
from infrastructure.embedding_service import EmbeddingService
from infrastructure.retrieval import EnhancedQueries, RetrievalDataError, RetrievalOutcome
from models.keyframe import Keyframe
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from repositories.object_repository import KeyframeObjectRepository
from repositories.text_repository import KeyframeTextRepository, TextSearchUnavailable
from repositories.traffic_repository import TrafficMetadataRepository
from repositories.vector_repository import KeyframeVectorRepository
from schemas.retrieval import ScoredCandidate
from schemas.search import (
    KISQueryPlan,
    KISQueryPlanEvent,
    KISSearchRequest,
    ObjectQueryTerm,
    QueryVariants,
    SearchRequest,
    SearchSources,
    SingleSearchResult,
    TrafficSearchRequest,
    TRAKEEventResult,
    TRAKESearchRequest,
    TRAKESearchResult,
)
from services.weights import object_terms_for, resolve_weights

logger = logging.getLogger(__name__)

__all__ = ["RetrievalDataError", "RetrievalService", "TrakeConfig"]

_SRRF_K = 60
_ASR_OVERFETCH = 3
_MAX_ASR_FETCH = 10_000
_PLAN_IMPORTANCE_WEIGHT = {"anchor": 1.0, "supporting": 0.6, "context": 0.2}
_ASR_UNAVAILABLE = "ASR search (Elasticsearch) is unavailable, so the ASR source was ignored."

# One element of a TRAKE beam: the candidate of an event and its temporal decay factor.
_BeamStep = tuple[ScoredCandidate, float]


@dataclass(frozen=True)
class TrakeConfig:
    """Temporal constraints of TRAKE sequences, in seconds of video time."""

    max_gap_seconds: float = 120.0
    decay_per_second: float = 0.010
    default_fps: float = 25.0


class RetrievalService:
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
        self._keyframe_repository = keyframe_repository
        self._vector_repos = {"siglip": siglip_vector_repo, "beit3": beit3_vector_repo}
        self._text_repository = text_repository
        self._blip2_reranker = blip2_reranker
        self._embedding_service = embedding_service
        self._intro_exclusion_policy = intro_exclusion_policy or IntroExclusionPolicy()
        self._object_repository = object_repository
        self._traffic_repository = traffic_repository
        self._fps_lookup = fps_lookup
        self._trake = trake_config or TrakeConfig()

    @property
    def _object_search_available(self) -> bool:
        return self._object_repository is not None and self._object_repository.available

    @property
    def _reranker_ready(self) -> bool:
        return self._blip2_reranker is not None and self._blip2_reranker.ready

    def retrieve(
        self, request: SearchRequest, enhanced_queries: EnhancedQueries = None
    ) -> RetrievalOutcome:
        warnings: list[str] = []
        results: tuple[SingleSearchResult | TRAKESearchResult, ...]
        if isinstance(request, TRAKESearchRequest):
            trake_queries = enhanced_queries if isinstance(enhanced_queries, dict) else None
            results = self._retrieve_trake(request, trake_queries, warnings)
        elif isinstance(request, KISSearchRequest) and isinstance(enhanced_queries, KISQueryPlan):
            results = self._retrieve_planned_kis(request, enhanced_queries, warnings)
        else:
            enhanced = enhanced_queries if isinstance(enhanced_queries, QueryVariants) else None
            allowed = None
            if isinstance(request, TrafficSearchRequest):
                if self._traffic_repository is None or not self._traffic_repository.available:
                    raise RetrievalDataError("Traffic metadata is not available")
                allowed = self._traffic_repository.allowed_mask(request.filters)
            elif isinstance(request, KISSearchRequest) and not request.include_traffic:
                allowed = self._non_traffic_mask()
            results = self._retrieve_single(request, enhanced, allowed, warnings)
        return RetrievalOutcome(results=results, warnings=tuple(dict.fromkeys(warnings)))

    def _non_traffic_mask(self) -> np.ndarray | None:
        """Keyframes outside the traffic videos, or None (no restriction) without traffic data."""
        if self._traffic_repository is None or not self._traffic_repository.available:
            return None
        return self._traffic_repository.non_traffic_mask()

    def _search_candidates(
        self,
        query: str,
        model_choices: list[str],
        fetch_k: int,
        sources: SearchSources,
        enhanced: QueryVariants | None,
        warnings: list[str],
        *,
        rerank: bool = False,
        asr_query: str | None = None,
        object_query: tuple[ObjectQueryTerm, ...] = (),
        allowed: np.ndarray | None = None,
    ) -> list[ScoredCandidate]:
        """Fused candidates; ``allowed`` (boolean mask over FAISS ids) restricts every modality.

        Fusion: each visual list is min-max normalized and accumulated as score / (60 + rank)
        (score-weighted RRF), the visual total is min-max normalized again, ASR BM25 scores are
        divided by the best hit and shared by every keyframe of a shot, object scores are
        already in [0, 1]. The modality weights are renormalized over the modalities that
        returned candidates.
        """
        object_terms = object_terms_for(
            sources, object_query, enhanced, self._object_search_available
        )
        weights = resolve_weights(sources, enhanced, object_query, object_terms)

        visual_queries = (enhanced.variants if enhanced else [query]) if weights.vis > 0 else []
        if not asr_query and enhanced and enhanced.asr_query_vi:
            # Spoken keywords sharpen BM25; the raw query keeps recall for paraphrases.
            asr_query = f"{enhanced.asr_query_vi} {query}"

        visual_lists = [
            self._intro_exclusion_policy.filter_candidates(
                self._vector_repos[model].search(self._embed(model, text), fetch_k, allowed)
            )
            for model in ("siglip", "beit3")
            if model in model_choices
            for text in visual_queries
        ]

        asr_cands: list[ScoredCandidate] = []
        if weights.asr > 0:
            try:
                # Every keyframe of a shot shares its transcript, so over-fetch to cover more shots.
                asr_cands = self._text_repository.search_text(
                    asr_query or query,
                    ["asr_text"],
                    min(fetch_k * _ASR_OVERFETCH, _MAX_ASR_FETCH),
                    allowed,
                )
            except TextSearchUnavailable:
                warnings.append(_ASR_UNAVAILABLE)
            asr_cands = self._intro_exclusion_policy.filter_candidates(asr_cands)

        obj_cands: list[ScoredCandidate] = []
        if weights.obj > 0 and self._object_repository is not None:
            obj_cands = self._object_repository.search(object_terms, fetch_k, allowed)

        cmap: dict[int, ScoredCandidate] = {}
        for cands in [*visual_lists, asr_cands, obj_cands]:
            for c in cands:
                cmap.setdefault(c.faiss_id, c)

        vis_norm = _min_max(_score_weighted_rrf(visual_lists))

        # BM25 is divided by the best hit so the weakest hit still counts, and a shot's
        # score is shared by all its keyframes, including visual candidates ASR missed.
        asr_by_segment: dict[str | int, float] = {}
        asr_max = max((c.similarity_score for c in asr_cands), default=0.0)
        for c in asr_cands:
            segment = c.keyframe.segment_id or c.faiss_id
            score = c.similarity_score / asr_max if asr_max > 0 else 0.0
            asr_by_segment[segment] = max(asr_by_segment.get(segment, 0.0), score)
        asr_norm = {
            faiss_id: asr_by_segment.get(c.keyframe.segment_id or faiss_id, 0.0)
            for faiss_id, c in cmap.items()
        }

        # Object scores are already in [0, 1] and comparable across keyframes, so every
        # candidate (not only the object top-k) is scored directly instead of normalized.
        obj_scores = (
            {
                faiss_id: self._object_repository.score(c.keyframe.keyframe_id, object_terms)
                for faiss_id, c in cmap.items()
            }
            if obj_cands and self._object_repository is not None
            else {}
        )

        # Weights are renormalized over modalities that returned candidates, so an empty
        # modality (e.g. ES offline) does not flatten the scores.
        w_vis = weights.vis if vis_norm else 0.0
        w_asr = weights.asr if asr_cands else 0.0
        w_obj = weights.obj if obj_cands else 0.0
        weight_sum = (w_vis + w_asr + w_obj) or 1.0
        final_scores = {
            faiss_id: (
                w_vis * vis_norm.get(faiss_id, 0.0)
                + w_asr * asr_norm.get(faiss_id, 0.0)
                + w_obj * obj_scores.get(faiss_id, 0.0)
            )
            / weight_sum
            for faiss_id in cmap
        }

        top_ids = sorted(final_scores, key=final_scores.__getitem__, reverse=True)[:fetch_k]
        candidates = [cmap[faiss_id].with_score(final_scores[faiss_id]) for faiss_id in top_ids]

        if rerank and self._reranker_ready:
            candidates = self._blip2_reranker.rerank(query, candidates)

        # Repository-level filters protect recall; this is a final invariant check
        # before any caller performs ranking or temporal reasoning.
        return self._intro_exclusion_policy.filter_candidates(candidates)

    def _embed(self, model: str, text: str) -> np.ndarray:
        if model == "siglip":
            return self._embedding_service.get_siglip_embedding(text)
        return self._embedding_service.get_beit3_embedding(text)

    def _retrieve_single(
        self,
        request: SearchRequest,
        enhanced: QueryVariants | None,
        allowed: np.ndarray | None,
        warnings: list[str],
    ) -> tuple[SingleSearchResult, ...]:
        candidates = self._search_candidates(
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
        return self._single_results_from_candidates(candidates[: request.top_k])

    def _retrieve_planned_kis(
        self, request: KISSearchRequest, plan: KISQueryPlan, warnings: list[str]
    ) -> tuple[SingleSearchResult, ...]:
        """Retrieve event frames, then rerank them with same-video event evidence."""
        fetch_k = max(request.top_k * 10, 100)
        primary_anchor = max(
            (event for event in plan.events if event.importance == "anchor"),
            key=lambda event: event.confidence,
        )
        retrieval_events = (primary_anchor,) if plan.search_mode == "single_anchor" else plan.events
        allowed = None if request.include_traffic else self._non_traffic_mask()

        candidates_by_event: dict[int, list[ScoredCandidate]] = {}
        for event in retrieval_events:
            visual_query = event.visual_query_en or event.source_span_vi
            candidates_by_event[event.event_index] = self._search_candidates(
                query=visual_query,
                model_choices=request.model_choices,
                fetch_k=fetch_k,
                sources=SearchSources(
                    image=bool(event.visual_query_en), asr=bool(event.asr_query_vi), object=False
                ),
                enhanced=QueryVariants(
                    variants=[visual_query],
                    w_vis=1.0 if event.visual_query_en else 0.0,
                    w_asr=1.0 if event.asr_query_vi else 0.0,
                ),
                warnings=warnings,
                rerank=request.use_reranking,
                asr_query=event.asr_query_vi,
                allowed=allowed,
            )

        anchor_candidates = candidates_by_event[primary_anchor.event_index]
        seeded: list[tuple[ScoredCandidate, KISQueryPlanEvent]] = [
            (candidate, primary_anchor) for candidate in anchor_candidates
        ]

        # Preserve all primary-anchor frames while allowing reliable secondary
        # events to contribute a few strong frames for each video. A target video
        # can already be present in the primary list with the wrong frame, so
        # expansion must be bounded by event and video rather than by video alone.
        seen_ids = {candidate.faiss_id for candidate in anchor_candidates}
        secondary_seed_counts: dict[tuple[int, str], int] = {}
        for event in retrieval_events:
            if not self._can_expand_plan_candidates(event, primary_anchor):
                continue
            for candidate in candidates_by_event[event.event_index]:
                if candidate.faiss_id in seen_ids:
                    continue
                seed_key = (event.event_index, candidate.keyframe.video_id)
                seed_count = secondary_seed_counts.get(seed_key, 0)
                if seed_count >= 3:
                    continue
                secondary_seed_counts[seed_key] = seed_count + 1
                seen_ids.add(candidate.faiss_id)
                seeded.append((candidate, event))

        scored_primary: list[tuple[float, ScoredCandidate]] = []
        scored_secondary: list[tuple[float, ScoredCandidate]] = []
        for seed_candidate, seed_event in seeded:
            weighted_score = seed_candidate.similarity_score
            total_weight = 1.0
            for event in retrieval_events:
                if event.event_index == seed_event.event_index:
                    continue
                weight = _PLAN_IMPORTANCE_WEIGHT[event.importance] * event.confidence
                weighted_score += weight * self._best_same_video_evidence(
                    candidates_by_event[event.event_index],
                    seed_candidate,
                    event,
                    seed_event,
                    plan.search_mode == "temporal_sequence",
                )
                total_weight += weight
            combined_score = weighted_score / total_weight
            if seed_event.event_index == primary_anchor.event_index:
                scored_primary.append((combined_score, seed_candidate))
            else:
                source_score = seed_event.confidence * seed_candidate.similarity_score
                scored_secondary.append((max(combined_score, source_score), seed_candidate))

        scored_primary.sort(key=lambda item: item[0], reverse=True)
        scored_secondary.sort(key=lambda item: item[0], reverse=True)
        if scored_secondary:
            protected_count = min(10, request.top_k, len(scored_primary))
            tail = scored_primary[protected_count:] + scored_secondary
            tail.sort(key=lambda item: item[0], reverse=True)
            scored = scored_primary[:protected_count] + tail[: request.top_k - protected_count]
        else:
            scored = scored_primary[: request.top_k]
        return self._single_results_from_candidates(
            [candidate.with_score(score) for score, candidate in scored]
        )

    @staticmethod
    def _can_expand_plan_candidates(
        event: KISQueryPlanEvent, primary_anchor: KISQueryPlanEvent
    ) -> bool:
        return (
            event.event_index != primary_anchor.event_index
            and event.importance in {"anchor", "supporting"}
            and event.confidence >= 0.8
            and not event.inferred
        )

    @staticmethod
    def _best_same_video_evidence(
        candidates: list[ScoredCandidate],
        anchor_candidate: ScoredCandidate,
        event: KISQueryPlanEvent,
        primary_anchor: KISQueryPlanEvent,
        enforce_order: bool,
    ) -> float:
        same_video = [
            candidate
            for candidate in candidates
            if candidate.keyframe.video_id == anchor_candidate.keyframe.video_id
        ]
        if not same_video:
            return 0.0
        if enforce_order:
            anchor_frame = anchor_candidate.keyframe.frame_id
            if event.event_index < primary_anchor.event_index:
                ordered = [c for c in same_video if c.keyframe.frame_id <= anchor_frame]
            else:
                ordered = [c for c in same_video if c.keyframe.frame_id >= anchor_frame]
            if ordered:
                return max(candidate.similarity_score for candidate in ordered)
            return 0.5 * max(candidate.similarity_score for candidate in same_video)
        return max(candidate.similarity_score for candidate in same_video)

    def _retrieve_trake(
        self,
        request: TRAKESearchRequest,
        enhanced_queries: dict[int, QueryVariants] | None,
        warnings: list[str],
    ) -> tuple[TRAKESearchResult, ...]:
        beam_width = max(150, request.top_k * 5)
        fetch_k = request.top_k * 10
        # TRAKE is never asked about the traffic videos, so they are left out entirely.
        allowed = self._non_traffic_mask()

        candidates_by_event = [
            self._search_candidates(
                event.query,
                request.model_choices,
                fetch_k,
                request.search_sources,
                enhanced_queries.get(event.event_index) if enhanced_queries else None,
                warnings,
                object_query=request.object_query,
                allowed=allowed,
            )
            for event in request.events
        ]
        if not candidates_by_event[0]:
            return ()

        beams: list[tuple[float, tuple[_BeamStep, ...]]] = [
            (c.similarity_score, ((c, 1.0),)) for c in candidates_by_event[0][:beam_width]
        ]
        for candidates in candidates_by_event[1:]:
            beams = self._extend_beams(beams, candidates)[:beam_width]
            if not beams:
                return ()

        gates = self._rerank_gates(request, beams)
        final_beams = []
        for _, sequence in beams:
            gated = [
                c.with_score(c.similarity_score * decay * gates[position].get(c.faiss_id, 1.0))
                for position, (c, decay) in enumerate(sequence)
            ]
            final_beams.append((sum(c.similarity_score for c in gated), gated))
        final_beams.sort(key=lambda item: item[0], reverse=True)

        return tuple(
            TRAKESearchResult(
                result_id=str(
                    uuid.uuid5(uuid.NAMESPACE_URL, "|".join(c.keyframe.keyframe_id for c in seq))
                ),
                rank=rank,
                video_id=seq[0].keyframe.video_id,
                similarity_score=total_score,
                events=tuple(
                    TRAKEEventResult(
                        event_index=position,
                        frame_id=c.keyframe.frame_id,
                        keyframe_url=_media_url(c.image_path),
                        segment_id=c.keyframe.segment_id or "",
                        asr_text=c.keyframe.asr_text or "",
                        objects=self._objects_for(c.keyframe),
                        similarity_score=c.similarity_score,
                    )
                    for position, c in enumerate(seq, start=1)
                ),
            )
            for rank, (total_score, seq) in enumerate(final_beams[: request.top_k], start=1)
        )

    def _extend_beams(
        self,
        beams: list[tuple[float, tuple[_BeamStep, ...]]],
        candidates: list[ScoredCandidate],
    ) -> list[tuple[float, tuple[_BeamStep, ...]]]:
        """Append every same-video candidate that comes later within the gap limit."""
        by_video: dict[str, list[ScoredCandidate]] = {}
        for candidate in candidates:
            by_video.setdefault(candidate.keyframe.video_id, []).append(candidate)
        frames_by_video: dict[str, list[int]] = {}
        for video_id, video_candidates in by_video.items():
            video_candidates.sort(key=lambda c: c.keyframe.frame_id)
            frames_by_video[video_id] = [c.keyframe.frame_id for c in video_candidates]

        next_beams = []
        for total_score, sequence in beams:
            last = sequence[-1][0].keyframe
            video_candidates = by_video.get(last.video_id)
            if not video_candidates:
                continue
            last_seconds = self._seconds(last)
            # Strictly later frames only.
            start = bisect_right(frames_by_video[last.video_id], last.frame_id)
            for candidate in video_candidates[start:]:
                delta = max(self._seconds(candidate.keyframe) - last_seconds, 0.0)
                if delta > self._trake.max_gap_seconds:
                    break
                decay = math.exp(-self._trake.decay_per_second * delta)
                next_beams.append(
                    (
                        total_score + candidate.similarity_score * decay,
                        (*sequence, (candidate, decay)),
                    )
                )
        next_beams.sort(key=lambda item: item[0], reverse=True)
        return next_beams

    def _rerank_gates(
        self,
        request: TRAKESearchRequest,
        beams: list[tuple[float, tuple[_BeamStep, ...]]],
    ) -> list[dict[int, float]]:
        """BLIP-2 match probability per event and FAISS id (multiplicative gating)."""
        gates: list[dict[int, float]] = [{} for _ in request.events]
        if not (request.use_reranking and self._reranker_ready):
            return gates
        for position, event in enumerate(request.events):
            unique = {
                sequence[position][0].faiss_id: sequence[position][0] for _, sequence in beams
            }
            probabilities = self._blip2_reranker.match_probabilities(
                event.query, [c.image_path for c in unique.values()]
            )
            gates[position] = dict(zip(unique, probabilities, strict=True))
        return gates

    def _seconds(self, keyframe: Keyframe) -> float:
        """Presentation time of a keyframe: time_ms when known (VFR), else frame_id / fps."""
        if keyframe.time_ms is not None:
            return keyframe.time_ms / 1000
        fps = self._fps_lookup(keyframe.video_id) if self._fps_lookup else None
        return keyframe.frame_id / (fps or self._trake.default_fps)

    def _single_results_from_candidates(
        self, candidates: list[ScoredCandidate]
    ) -> tuple[SingleSearchResult, ...]:
        return tuple(
            SingleSearchResult(
                result_id=candidate.keyframe.keyframe_id,
                rank=rank,
                video_id=candidate.keyframe.video_id,
                frame_id=candidate.keyframe.frame_id,
                keyframe_url=_media_url(candidate.image_path),
                image_path=candidate.image_path,
                segment_id=candidate.keyframe.segment_id or "",
                asr_text=candidate.keyframe.asr_text or "",
                objects=self._objects_for(candidate.keyframe),
                similarity_score=candidate.similarity_score,
                answer="",
                time_ms=candidate.keyframe.time_ms,
                **self._traffic_fields(candidate.keyframe),
            )
            for rank, candidate in enumerate(candidates, start=1)
        )

    def _traffic_fields(self, keyframe: Keyframe) -> dict[str, str | None]:
        if self._traffic_repository is None:
            return {}
        video = self._traffic_repository.video(keyframe.video_id)
        if video is None:
            return {}
        clock = self._traffic_repository.clock_time(keyframe)
        return {
            "camera_name": video.camera_name,
            "clock_time": clock.strftime("%d/%m %H:%M:%S") if clock else None,
            "weather": video.weather or None,
        }

    def _objects_for(self, keyframe: Keyframe) -> list[dict]:
        if keyframe.objects:
            return keyframe.objects
        if self._object_repository is None:
            return []
        return self._object_repository.objects_for(keyframe.keyframe_id)


def _media_url(image_path: str) -> str:
    # Served by the /media mount; stable URLs let the browser cache keyframes across searches.
    return f"/media/{image_path}"


def _score_weighted_rrf(lists: list[list[ScoredCandidate]]) -> dict[int, float]:
    """Sum over lists of the min-max normalized score divided by (60 + rank)."""
    fused: dict[int, float] = {}
    for candidates in lists:
        if not candidates:
            continue
        max_s = max(c.similarity_score for c in candidates)
        min_s = min(c.similarity_score for c in candidates)
        range_s = max_s - min_s if max_s > min_s else 1.0
        for rank, c in enumerate(candidates, start=1):
            norm_score = (c.similarity_score - min_s) / range_s
            fused[c.faiss_id] = fused.get(c.faiss_id, 0.0) + norm_score / (_SRRF_K + rank)
    return fused


def _min_max(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    max_s, min_s = max(scores.values()), min(scores.values())
    range_s = max_s - min_s + 1e-6
    return {key: (value - min_s) / range_s for key, value in scores.items()}
