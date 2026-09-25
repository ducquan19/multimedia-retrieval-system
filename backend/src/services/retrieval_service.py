import logging
import math
import time
import uuid

import numpy as np

from core.constants import MANUAL_OBJECT_WEIGHT
from core.intro_exclusion import IntroExclusionPolicy
from infrastructure.blip2_reranker import BLIP2Reranker
from infrastructure.embedding_service import EmbeddingService
from models.keyframe import Keyframe
from repositories.object_repository import KeyframeObjectRepository
from repositories.text_repository import KeyframeTextRepository
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
    TRAKEEventResult,
    TRAKESearchRequest,
    TRAKESearchResult,
    TrafficSearchRequest,
)

logger = logging.getLogger(__name__)


class RetrievalDataError(RuntimeError):
    """Raised when retrieval data (like vectors or text index) is missing or corrupted."""


class RetrievalService:
    def __init__(
        self,
        siglip_vector_repo: KeyframeVectorRepository,
        beit3_vector_repo: KeyframeVectorRepository,
        text_repository: KeyframeTextRepository,
        blip2_reranker: BLIP2Reranker,
        embedding_service: EmbeddingService,
        intro_exclusion_policy: IntroExclusionPolicy | None = None,
        object_repository: KeyframeObjectRepository | None = None,
        traffic_repository: TrafficMetadataRepository | None = None,
    ) -> None:
        self._siglip_repo = siglip_vector_repo
        self._beit3_repo = beit3_vector_repo
        self._text_repository = text_repository
        self._blip2_reranker = blip2_reranker
        self._embedding_service = embedding_service
        self._intro_exclusion_policy = intro_exclusion_policy or IntroExclusionPolicy()
        self._object_repository = object_repository
        self._traffic_repository = traffic_repository

    def retrieve(
        self,
        request: SearchRequest,
        enhanced_queries: QueryVariants | dict[int, QueryVariants] | KISQueryPlan | None = None,
    ) -> tuple[SingleSearchResult | TRAKESearchResult, ...]:
        if isinstance(request, TRAKESearchRequest):
            trake_queries = enhanced_queries if isinstance(enhanced_queries, dict) else None
            return self._retrieve_trake(request, trake_queries)
        if isinstance(request, KISSearchRequest) and isinstance(enhanced_queries, KISQueryPlan):
            return self._retrieve_planned_kis(request, enhanced_queries)
        enhanced = enhanced_queries if isinstance(enhanced_queries, QueryVariants) else None
        allowed_ids = None
        if isinstance(request, TrafficSearchRequest):
            if self._traffic_repository is None or not self._traffic_repository.available:
                raise RetrievalDataError("Traffic metadata is not available")
            allowed_ids = self._traffic_repository.allowed_ids(request.filters)
        return self._retrieve_single(request, enhanced, allowed_ids)

    def _search_candidates(
        self,
        query: str,
        model_choices: list[str],
        fetch_k: int,
        search_sources=None,
        enhanced: QueryVariants | None = None,
        use_reranking: bool = False,
        asr_query: str | None = None,
        object_query: tuple[ObjectQueryTerm, ...] = (),
        allowed_ids: np.ndarray | None = None,
    ) -> list[ScoredCandidate]:
        """Fused candidates; ``allowed_ids`` restricts every modality to those FAISS ids."""
        use_image = getattr(search_sources, "image", True)
        use_asr = getattr(search_sources, "asr", False)
        use_object = getattr(search_sources, "object", False)

        # Manual object terms come first; Gemini only adds labels that are not already there.
        object_terms = self._merge_object_terms(
            object_query, enhanced.objects if enhanced else ()
        )
        if not use_object or self._object_repository is None:
            object_terms = ()

        # Sources are the modalities the user allows; Gemini weights modulate them.
        if enhanced:
            w_vis = enhanced.w_vis if use_image else 0.0
            w_asr = enhanced.w_asr if use_asr else 0.0
            w_obj = enhanced.w_obj if enhanced.objects else 0.0
            if object_query:
                w_obj = max(w_obj, MANUAL_OBJECT_WEIGHT)
            w_obj = w_obj if object_terms else 0.0
            if w_vis + w_asr + w_obj == 0:
                # Gemini weighted only disabled modalities: fall back to the enabled ones.
                w_vis = 1.0 if use_image else 0.0
                w_asr = 1.0 if use_asr else 0.0
                w_obj = 1.0 if object_terms else 0.0
        else:
            w_vis = 1.0 if use_image else 0.0
            w_asr = 1.0 if use_asr else 0.0
            w_obj = 1.0 if object_terms else 0.0

        visual_queries = (enhanced.variants if enhanced else [query]) if w_vis > 0 else []
        if not asr_query and enhanced and enhanced.asr_query_vi:
            # Spoken keywords sharpen BM25; the raw query keeps recall for paraphrases.
            asr_query = f"{enhanced.asr_query_vi} {query}"

        siglip_candidates_lists = []
        beit3_candidates_lists = []

        if "siglip" in model_choices:
            for vq in visual_queries:
                query_vector = self._embedding_service.get_siglip_embedding(vq)
                siglip_candidates_lists.append(
                    self._siglip_repo.search(query_vector, fetch_k, allowed_ids)
                )

        if "beit3" in model_choices:
            for vq in visual_queries:
                query_vector = self._embedding_service.get_beit3_embedding(vq)
                beit3_candidates_lists.append(
                    self._beit3_repo.search(query_vector, fetch_k, allowed_ids)
                )

        asr_cands = []
        if w_asr > 0:
            # Every keyframe of a shot shares its transcript, so over-fetch to cover more shots.
            asr_cands = self._text_repository.search_text(
                asr_query or query, ["asr_text"], None, min(fetch_k * 3, 10_000)
            )
            if allowed_ids is not None:
                allowed_keyframes = self._keyframe_ids(allowed_ids)
                asr_cands = [c for c in asr_cands if c.keyframe.keyframe_id in allowed_keyframes]

        siglip_candidates_lists = [
            self._intro_exclusion_policy.filter_candidates(candidates)
            for candidates in siglip_candidates_lists
        ]
        beit3_candidates_lists = [
            self._intro_exclusion_policy.filter_candidates(candidates)
            for candidates in beit3_candidates_lists
        ]
        asr_cands = self._intro_exclusion_policy.filter_candidates(asr_cands)

        obj_cands = []
        if w_obj > 0:
            allowed = None
            if allowed_ids is not None:
                allowed = self._keyframe_ids(allowed_ids).__contains__
            obj_cands = self._object_repository.search(object_terms, fetch_k, allowed)

        cmap = {}
        for cands in siglip_candidates_lists + beit3_candidates_lists + [asr_cands, obj_cands]:
            for c in cands:
                if c.image_path not in cmap:
                    cmap[c.image_path] = c

        # 1. Visual SRRF (for fusing SigLIP and BEiT-3)
        vis_srrf = {}

        def add_to_srrf(cands: list["ScoredCandidate"], k=60):
            if not cands:
                return
            max_s = max(c.similarity_score for c in cands)
            min_s = min(c.similarity_score for c in cands)
            range_s = max_s - min_s if max_s > min_s else 1.0
            for rank, c in enumerate(cands, start=1):
                norm_score = (c.similarity_score - min_s) / range_s
                vis_srrf[c.image_path] = vis_srrf.get(c.image_path, 0.0) + norm_score / (k + rank)

        for cands in siglip_candidates_lists:
            add_to_srrf(cands)
        for cands in beit3_candidates_lists:
            add_to_srrf(cands)

        # 2. Min-Max Normalization
        def norm_dict(d: dict[str, float]) -> dict[str, float]:
            if not d:
                return {}
            max_s, min_s = max(d.values()), min(d.values())
            range_s = max_s - min_s + 1e-6
            return {k: (v - min_s) / range_s for k, v in d.items()}

        vis_norm = norm_dict(vis_srrf)

        # BM25 is divided by the best hit so the weakest hit still counts, and a shot's
        # score is shared by all its keyframes, including visual candidates ASR missed.
        asr_by_segment: dict[str, float] = {}
        asr_max = max((c.similarity_score for c in asr_cands), default=0.0)
        for c in asr_cands:
            segment = c.keyframe.segment_id or c.image_path
            score = c.similarity_score / asr_max if asr_max > 0 else 0.0
            asr_by_segment[segment] = max(asr_by_segment.get(segment, 0.0), score)
        asr_norm = {
            p: asr_by_segment.get(c.keyframe.segment_id or p, 0.0) for p, c in cmap.items()
        }

        # Object scores are already in [0, 1] and comparable across keyframes, so every
        # candidate (not only the object top-k) is scored directly instead of normalized.
        obj_scores = (
            {
                p: self._object_repository.score(c.keyframe.keyframe_id, object_terms)
                for p, c in cmap.items()
            }
            if w_obj > 0
            else {}
        )

        # 3. Final Score Fusion: weights are renormalized over modalities that returned
        # candidates, so an empty modality (e.g. ES offline) does not flatten the scores.
        active_weights = {
            "vis": w_vis if vis_norm else 0.0,
            "asr": w_asr if asr_cands else 0.0,
            "obj": w_obj if obj_cands else 0.0,
        }
        weight_sum = sum(active_weights.values()) or 1.0
        final_scores = {}
        for p in cmap:
            final_scores[p] = (
                active_weights["vis"] * vis_norm.get(p, 0.0)
                + active_weights["asr"] * asr_norm.get(p, 0.0)
                + active_weights["obj"] * obj_scores.get(p, 0.0)
            ) / weight_sum

        top_paths = sorted(final_scores.keys(), key=lambda x: final_scores[x], reverse=True)[
            :fetch_k
        ]
        candidates = [
            cmap[p].model_copy(update={"similarity_score": final_scores[p]}) for p in top_paths
        ]

        if self._blip2_reranker.enable and use_reranking:
            candidates = self._blip2_reranker.rerank(query, candidates)

        # Repository-level filters protect recall; this is a final invariant check
        # before any caller performs ranking or temporal reasoning.
        return self._intro_exclusion_policy.filter_candidates(candidates)

    def _keyframe_ids(self, faiss_ids: np.ndarray) -> set[str]:
        keyframes = self._siglip_repo.keyframe_repository.load().keyframes
        return {keyframes[i].keyframe_id for i in faiss_ids.tolist()}

    @staticmethod
    def _merge_object_terms(
        manual: tuple[ObjectQueryTerm, ...], automatic: tuple[ObjectQueryTerm, ...]
    ) -> tuple[ObjectQueryTerm, ...]:
        labels = {term.label.casefold() for term in manual}
        return manual + tuple(term for term in automatic if term.label.casefold() not in labels)

    def _retrieve_single(
        self,
        request: SearchRequest,
        enhanced_queries: QueryVariants | None = None,
        allowed_ids: np.ndarray | None = None,
    ) -> tuple[SingleSearchResult, ...]:
        model_choices = getattr(request, "model_choices", ["siglip"])
        fetch_k = request.top_k * 5

        search_sources = getattr(request, "search_sources", None)

        candidates = self._search_candidates(
            request.query,
            model_choices,
            fetch_k,
            search_sources,
            enhanced_queries,
            getattr(request, "use_reranking", False),
            object_query=request.object_query,
            allowed_ids=allowed_ids,
        )
        return self._single_results_from_candidates(candidates[: request.top_k])

    def _retrieve_planned_kis(
        self, request: KISSearchRequest, plan: KISQueryPlan
    ) -> tuple[SingleSearchResult, ...]:
        """Retrieve event frames, then rerank them with same-video event evidence."""
        fetch_k = max(request.top_k * 10, 100)
        primary_anchor = max(
            (event for event in plan.events if event.importance == "anchor"),
            key=lambda event: event.confidence,
        )
        candidates_by_event: dict[int, list[ScoredCandidate]] = {}
        retrieval_events = (primary_anchor,) if plan.search_mode == "single_anchor" else plan.events

        for event in retrieval_events:
            sources = SearchSources(
                image=bool(event.visual_query_en),
                asr=bool(event.asr_query_vi),
                object=False,
            )
            visual_query = event.visual_query_en or event.source_span_vi
            enhanced = QueryVariants(
                variants=[visual_query],
                w_vis=1.0 if event.visual_query_en else 0.0,
                w_asr=1.0 if event.asr_query_vi else 0.0,
            )
            candidates_by_event[event.event_index] = self._search_candidates(
                query=visual_query,
                model_choices=request.model_choices,
                fetch_k=fetch_k,
                search_sources=sources,
                enhanced=enhanced,
                use_reranking=request.use_reranking,
                asr_query=event.asr_query_vi,
            )

        anchor_candidates = candidates_by_event[primary_anchor.event_index]
        seeded_candidates: list[tuple[ScoredCandidate, KISQueryPlanEvent]] = [
            (candidate, primary_anchor) for candidate in anchor_candidates
        ]

        # Preserve all primary-anchor frames while allowing reliable secondary
        # events to contribute a few strong frames for each video. A target video
        # can already be present in the primary list with the wrong frame, so
        # expansion must be bounded by event and video rather than by video alone.
        primary_image_paths = {candidate.image_path for candidate in anchor_candidates}
        secondary_seeds: list[tuple[ScoredCandidate, KISQueryPlanEvent]] = []
        secondary_seed_counts: dict[tuple[int, str], int] = {}
        for event in retrieval_events:
            if not self._can_expand_plan_candidates(event, primary_anchor):
                continue
            for candidate in candidates_by_event[event.event_index]:
                if candidate.image_path in primary_image_paths:
                    continue
                video_id = candidate.keyframe.video_id
                seed_key = (event.event_index, video_id)
                seed_count = secondary_seed_counts.get(seed_key, 0)
                if seed_count >= 3:
                    continue
                secondary_seed_counts[seed_key] = seed_count + 1
                secondary_seeds.append((candidate, event))
        seeded_candidates.extend(secondary_seeds)

        scored_primary: list[tuple[float, ScoredCandidate]] = []
        scored_secondary: list[tuple[float, ScoredCandidate]] = []
        for seed_candidate, seed_event in seeded_candidates:
            weighted_score = seed_candidate.similarity_score
            total_weight = 1.0
            for event in retrieval_events:
                if event.event_index == seed_event.event_index:
                    continue
                weight = self._plan_event_weight(event)
                evidence_score = self._best_same_video_evidence(
                    candidates_by_event[event.event_index],
                    seed_candidate,
                    event,
                    seed_event,
                    plan.search_mode == "temporal_sequence",
                )
                weighted_score += weight * evidence_score
                total_weight += weight
            combined_score = weighted_score / total_weight
            if seed_event.event_index == primary_anchor.event_index:
                scored_primary.append((combined_score, seed_candidate))
            else:
                source_score = seed_event.confidence * seed_candidate.similarity_score
                scored_secondary.append(
                    (max(combined_score, source_score), seed_candidate)
                )

        scored_primary.sort(key=lambda item: item[0], reverse=True)
        scored_secondary.sort(key=lambda item: item[0], reverse=True)
        if scored_secondary:
            protected_count = min(10, request.top_k, len(scored_primary))
            protected = scored_primary[:protected_count]
            tail = scored_primary[protected_count:] + scored_secondary
            tail.sort(key=lambda item: item[0], reverse=True)
            scored = protected + tail[: request.top_k - protected_count]
        else:
            scored = scored_primary[: request.top_k]
        reranked = [
            candidate.model_copy(update={"similarity_score": score})
            for score, candidate in scored
        ]
        return self._single_results_from_candidates(reranked)

    @staticmethod
    def _plan_event_weight(event: KISQueryPlanEvent) -> float:
        importance_weight = {"anchor": 1.0, "supporting": 0.6, "context": 0.2}
        return importance_weight[event.importance] * event.confidence

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
            if event.event_index < primary_anchor.event_index:
                ordered = [
                    candidate
                    for candidate in same_video
                    if candidate.keyframe.frame_id <= anchor_candidate.keyframe.frame_id
                ]
            else:
                ordered = [
                    candidate
                    for candidate in same_video
                    if candidate.keyframe.frame_id >= anchor_candidate.keyframe.frame_id
                ]
            if ordered:
                return max(candidate.similarity_score for candidate in ordered)
            return 0.5 * max(candidate.similarity_score for candidate in same_video)
        return max(candidate.similarity_score for candidate in same_video)

    def _single_results_from_candidates(
        self, candidates: list[ScoredCandidate]
    ) -> tuple[SingleSearchResult, ...]:
        results = []
        for rank, candidate in enumerate(candidates, start=1):
            keyframe = candidate.keyframe
            results.append(
                SingleSearchResult(
                    result_id=candidate.result_id,
                    rank=rank,
                    video_id=keyframe.video_id,
                    frame_id=keyframe.frame_id,
                    keyframe_url=self._media_url(keyframe.image_path),
                    image_path=keyframe.image_path,
                    segment_id=keyframe.segment_id or "",
                    asr_text=keyframe.asr_text or "",
                    objects=self._objects_for(keyframe),
                    similarity_score=candidate.similarity_score,
                    answer="",
                    time_ms=keyframe.time_ms,
                    **self._traffic_fields(keyframe),
                )
            )
        return tuple(results)

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

    def _retrieve_trake(
        self, request: TRAKESearchRequest, enhanced_queries: dict[int, QueryVariants] | None = None
    ) -> tuple[TRAKESearchResult, ...]:
        if not request.events:
            return tuple()

        beam_width = max(150, request.top_k * 5)
        max_kf_gap = getattr(request, "max_kf_gap", 3000)  # Defaults to 3000 gap if not provided
        model_choices = getattr(request, "model_choices", ["siglip"])
        fetch_k = request.top_k * 10
        search_sources = getattr(request, "search_sources", None)
        use_reranking = getattr(request, "use_reranking", False)
        # TRAKE is never asked about the traffic videos, so they are left out entirely.
        allowed_ids = (
            self._traffic_repository.non_traffic_ids()
            if self._traffic_repository is not None and self._traffic_repository.available
            else None
        )

        # 1. Forward Pass: Fetch candidates for all events using per-event enhanced queries
        first_event = request.events[0]
        enhanced_for_first = (
            enhanced_queries.get(first_event.event_index) if enhanced_queries else None
        )

        first_candidates = self._search_candidates(
            first_event.query,
            model_choices,
            fetch_k,
            search_sources,
            enhanced_for_first,
            use_reranking,
            object_query=request.object_query,
            allowed_ids=allowed_ids,
        )

        if not first_candidates:
            return tuple()

        # beam = [(total_score, [(ScoredCandidate, s_i, lambda_i)])]
        beams: list[tuple[float, list[tuple[ScoredCandidate, float, float]]]] = [
            (c.similarity_score, [(c, c.similarity_score, 1.0)])
            for c in first_candidates[:beam_width]
        ]

        # Stages 2..N
        for event in request.events[1:]:
            event_enhanced = enhanced_queries.get(event.event_index) if enhanced_queries else None
            candidates = self._search_candidates(
                event.query,
                model_choices,
                fetch_k,
                search_sources,
                event_enhanced,
                object_query=request.object_query,
                allowed_ids=allowed_ids,
            )
            next_beams: list[tuple[float, list[tuple[ScoredCandidate, float, float]]]] = []

            for total_score, seq in beams:
                last_c_tuple = seq[-1]
                last_c = last_c_tuple[0]
                for c in candidates:
                    # Constraint 1: Same video
                    if c.keyframe.video_id != last_c.keyframe.video_id:
                        continue
                    # Constraint 2: Strictly increasing frame_id
                    if c.keyframe.frame_id <= last_c.keyframe.frame_id:
                        continue
                    # Constraint 3: Gap limit
                    if c.keyframe.frame_id - last_c.keyframe.frame_id > max_kf_gap:
                        continue

                    # Exponential Decay Penalty
                    delta_t = (c.keyframe.frame_id - last_c.keyframe.frame_id) / 25.0
                    decay = math.exp(-0.010 * delta_t)

                    next_beams.append(
                        (
                            total_score + c.similarity_score * decay,
                            seq + [(c, c.similarity_score, decay)],
                        )
                    )

            next_beams.sort(key=lambda x: x[0], reverse=True)
            beams = next_beams[:beam_width]

            if not beams:
                return tuple()

        # Stage 4: BLIP-2 Multiplicative Gating
        final_beams = []
        for _total_score, seq in beams:
            final_seq_score = 0.0
            gated_seq = []
            for i, (c, s_i, lambda_i) in enumerate(seq):
                event_query = request.events[i].query

                if getattr(request, "use_reranking", False) and self._blip2_reranker.enable:
                    # BLIP-2 returns the candidate with updated similarity_score
                    b_i = self._blip2_reranker.rerank(event_query, [c])[0].similarity_score
                else:
                    b_i = 1.0

                final_event_score = s_i * lambda_i * b_i
                final_seq_score += final_event_score

                gated_c = c.model_copy(update={"similarity_score": final_event_score})
                gated_seq.append(gated_c)

            final_beams.append((final_seq_score, gated_seq))

        final_beams.sort(key=lambda x: x[0], reverse=True)

        # Convert the top K beams into TRAKESearchResult
        results = []
        for rank, (total_score, seq) in enumerate(final_beams[: request.top_k], start=1):
            event_results = []
            for i, c in enumerate(seq):
                event_results.append(
                    TRAKEEventResult(
                        event_index=i + 1,
                        frame_id=c.keyframe.frame_id,
                        keyframe_url=self._media_url(c.image_path),
                        segment_id=c.keyframe.segment_id or "",
                        asr_text=c.keyframe.asr_text or "",
                        objects=self._objects_for(c.keyframe),
                        similarity_score=c.similarity_score,
                    )
                )

            results.append(
                TRAKESearchResult(
                    result_id=str(uuid.uuid4()),
                    rank=rank,
                    video_id=seq[0].keyframe.video_id,
                    similarity_score=total_score,
                    events=tuple(event_results),
                )
            )

        return tuple(results)

    def _objects_for(self, keyframe: Keyframe) -> list[dict]:
        if keyframe.objects:
            return keyframe.objects
        if self._object_repository is None:
            return []
        return self._object_repository.objects_for(keyframe.keyframe_id)

    @staticmethod
    def _media_url(image_path: str) -> str:
        # Assumes the frontend is proxying /media requests to the backend /media endpoint
        return f"/media/{image_path}?cb={int(time.time())}"
