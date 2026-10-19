"""KIS search driven by a Query Understanding & Planning plan."""

import numpy as np

from models.candidate import ScoredCandidate
from models.query import KISQueryPlan, KISQueryPlanEvent, QueryVariants, SearchSources
from schemas.search import KISSearchRequest
from services.retrieval.fusion import CandidateSearch

_PLAN_IMPORTANCE_WEIGHT = {"anchor": 1.0, "supporting": 0.6, "context": 0.2}


class PlannedKisSearch:
    """Retrieve frames per plan event, then rerank them with same-video event evidence."""

    def __init__(self, candidate_search: CandidateSearch) -> None:
        self._candidate_search = candidate_search

    def search(
        self,
        request: KISSearchRequest,
        plan: KISQueryPlan,
        allowed: np.ndarray | None,
        warnings: list[str],
    ) -> list[ScoredCandidate]:
        fetch_k = max(request.top_k * 10, 100)
        primary_anchor = max(
            (event for event in plan.events if event.importance == "anchor"),
            key=lambda event: event.confidence,
        )
        retrieval_events = (primary_anchor,) if plan.search_mode == "single_anchor" else plan.events

        candidates_by_event: dict[int, list[ScoredCandidate]] = {}
        for event in retrieval_events:
            visual_query = event.visual_query_en or event.source_span_vi
            candidates_by_event[event.event_index] = self._candidate_search.search(
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

        # Preserve all primary-anchor frames while allowing reliable secondary events to
        # contribute a few strong frames for each video. A target video can already be present
        # in the primary list with the wrong frame, so expansion must be bounded by event and
        # video rather than by video alone.
        seen_ids = {candidate.faiss_id for candidate in anchor_candidates}
        secondary_seed_counts: dict[tuple[int, str], int] = {}
        for event in retrieval_events:
            if not _can_expand_plan_candidates(event, primary_anchor):
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
                weighted_score += weight * _best_same_video_evidence(
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
        return [candidate.with_score(score) for score, candidate in scored]


def _can_expand_plan_candidates(
    event: KISQueryPlanEvent, primary_anchor: KISQueryPlanEvent
) -> bool:
    return (
        event.event_index != primary_anchor.event_index
        and event.importance in {"anchor", "supporting"}
        and event.confidence >= 0.8
        and not event.inferred
    )


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
