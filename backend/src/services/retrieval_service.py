import logging
import uuid
import time
from typing import Any

from infrastructure.blip2_reranker import BLIP2Reranker
from infrastructure.embedding_service import EmbeddingService
from repositories.text_repository import KeyframeTextRepository
from repositories.vector_repository import KeyframeVectorRepository
from schemas.retrieval import ScoredCandidate
from schemas.search import (
    SearchRequest,
    SingleSearchResult,
    TRAKESearchRequest,
    TRAKESearchResult,
    TRAKEEventResult,
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
    ) -> None:
        self._siglip_repo = siglip_vector_repo
        self._beit3_repo = beit3_vector_repo
        self._text_repository = text_repository
        self._blip2_reranker = blip2_reranker
        self._embedding_service = embedding_service

    def retrieve(
        self, request: SearchRequest
    ) -> tuple[SingleSearchResult | TRAKESearchResult, ...]:
        if isinstance(request, TRAKESearchRequest):
            return self._retrieve_trake(request)
        return self._retrieve_single(request)

    def _search_candidates(self, query: str, model_choice: str, fetch_k: int) -> list[ScoredCandidate]:
        if model_choice == "siglip":
            query_vector = self._embedding_service.get_siglip_embedding(query)
            candidates = self._siglip_repo.search(query_vector, fetch_k)
        elif model_choice == "beit3":
            query_vector = self._embedding_service.get_beit3_embedding(query)
            candidates = self._beit3_repo.search(query_vector, fetch_k)
        else:
            # Hybrid search
            siglip_vector = self._embedding_service.get_siglip_embedding(query)
            beit3_vector = self._embedding_service.get_beit3_embedding(query)

            siglip_candidates = self._siglip_repo.search(siglip_vector, fetch_k)
            beit3_candidates = self._beit3_repo.search(beit3_vector, fetch_k)
            es_candidates = self._text_repository.search_metadata(query, None, fetch_k)

            def get_rrf(cands: list['ScoredCandidate'], k=60) -> dict[str, float]:
                return {c.image_path: 1.0 / (k + rank) for rank, c in enumerate(cands, start=1)}

            siglip_rrf = get_rrf(siglip_candidates)
            beit3_rrf = get_rrf(beit3_candidates)
            es_rrf = get_rrf(es_candidates)

            siglip_raw = {c.image_path: c.similarity_score for c in siglip_candidates}
            beit3_raw = {c.image_path: c.similarity_score for c in beit3_candidates}
            es_raw = {c.image_path: c.similarity_score for c in es_candidates}

            all_paths = set(siglip_rrf.keys()) | set(beit3_rrf.keys()) | set(es_rrf.keys())
            fused = {}
            for path in all_paths:
                fused[path] = siglip_rrf.get(path, 0.0) + beit3_rrf.get(path, 0.0) + es_rrf.get(path, 0.0)

            top_paths = sorted(fused.keys(), key=lambda x: fused[x], reverse=True)[:fetch_k]

            cmap = {c.image_path: c for c in siglip_candidates + beit3_candidates + es_candidates}
            candidates = []
            for path in top_paths:
                c = cmap[path]
                # Keep RRF for ranking, but show the max raw similarity score for UI
                max_raw_score = max(siglip_raw.get(path, 0.0), beit3_raw.get(path, 0.0), es_raw.get(path, 0.0))
                candidates.append(c.model_copy(update={"similarity_score": max_raw_score}))

        # 3. BLIP-2 Reranking
        if self._blip2_reranker.enable:
            candidates = self._blip2_reranker.rerank(query, candidates)

        return candidates

    def _retrieve_single(self, request: SearchRequest) -> tuple[SingleSearchResult, ...]:
        model_choice = getattr(request, "model_choice", "hybrid")
        fetch_k = request.top_k * 5

        candidates = self._search_candidates(request.query, model_choice, fetch_k)

        # Normalize scores to 0-1 for UI display purposes
        if candidates:
            max_score = candidates[0].similarity_score
            min_score = candidates[-1].similarity_score
            score_range = max_score - min_score

            scaled_candidates = []
            if score_range > 1e-9:
                for c in candidates:
                    scaled_candidates.append(
                        c.model_copy(update={"similarity_score": (c.similarity_score - min_score) / score_range})
                    )
            else:
                for c in candidates:
                    scaled_candidates.append(
                        c.model_copy(update={"similarity_score": 1.0})
                    )
            candidates = scaled_candidates

        results = []
        for rank, candidate in enumerate(candidates[: request.top_k], start=1):
            keyframe = candidate.keyframe
            results.append(
                SingleSearchResult(
                    result_id=candidate.result_id,
                    rank=rank,
                    video_id=keyframe.video_id,
                    frame_id=keyframe.frame_id,
                    keyframe_url=self._media_url(keyframe.image_path),
                    segment_id=keyframe.segment_id or "",
                    asr_text=keyframe.asr_text or "",
                    ocr_text=keyframe.ocr_text or "",
                    objects=keyframe.objects or [],
                    similarity_score=candidate.similarity_score,
                    answer="",
                )
            )

        return tuple(results)

    def _retrieve_trake(self, request: TRAKESearchRequest) -> tuple[TRAKESearchResult, ...]:
        if not request.events:
            return tuple()

        beam_width = min(request.top_k * 5, 100)
        max_kf_gap = getattr(request, "max_kf_gap", 200) # Defaults to 200 gap if not provided
        model_choice = getattr(request, "model_choice", "hybrid")

        # Stage 1: Get top-K for the first event
        first_event_query = request.events[0].query
        first_candidates = self._search_candidates(first_event_query, model_choice, beam_width)

        if not first_candidates:
            return tuple()

        # beam = [(total_score, [ScoredCandidate seq])]
        beams: list[tuple[float, list[ScoredCandidate]]] = [
            (c.similarity_score, [c]) for c in first_candidates
        ]

        # Stages 2..N
        for event in request.events[1:]:
            candidates = self._search_candidates(event.query, model_choice, min(beam_width * 20, 200))
            next_beams: list[tuple[float, list[ScoredCandidate]]] = []

            for total_score, seq in beams:
                last_c = seq[-1]
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

                    next_beams.append((total_score + c.similarity_score, seq + [c]))

            next_beams.sort(key=lambda x: x[0], reverse=True)
            beams = next_beams[:beam_width]

            if not beams:
                return tuple()

        # Convert the top K beams into TRAKESearchResult
        # We'll take the top_k best sequences
        results = []
        for rank, (total_score, seq) in enumerate(beams[:request.top_k], start=1):
            event_results = []
            for i, c in enumerate(seq):
                event_results.append(
                    TRAKEEventResult(
                        event_index=i + 1,
                        frame_id=c.keyframe.frame_id,
                        keyframe_url=self._media_url(c.image_path),
                        segment_id=c.keyframe.segment_id or "",
                        asr_text=c.keyframe.asr_text or "",
                        ocr_text=c.keyframe.ocr_text or "",
                        objects=c.keyframe.objects or [],
                        similarity_score=c.similarity_score,
                    )
                )

            results.append(
                TRAKESearchResult(
                    result_id=str(uuid.uuid4()),
                    rank=rank,
                    video_id=seq[0].keyframe.video_id,
                    similarity_score=total_score,
                    events=tuple(event_results)
                )
            )

        return tuple(results)

    @staticmethod
    def _media_url(image_path: str) -> str:
        # Assumes the frontend is proxying /media requests to the backend /media endpoint
        return f"/media/{image_path}?cb={int(time.time())}"
