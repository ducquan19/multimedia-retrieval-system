import logging
import uuid
import time
import math
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
        self, request: SearchRequest, enhanced_queries: list[str] | dict[int, list[str]] | None = None
    ) -> tuple[SingleSearchResult | TRAKESearchResult, ...]:
        if isinstance(request, TRAKESearchRequest):
            return self._retrieve_trake(request, enhanced_queries)
        return self._retrieve_single(request, enhanced_queries)

    def _search_candidates(
        self, query: str, model_choices: list[str], fetch_k: int, search_sources=None, enhanced_queries: list[str] | None = None, use_reranking: bool = False
    ) -> list[ScoredCandidate]:
        visual_queries = enhanced_queries if enhanced_queries else [query]

        siglip_candidates_lists = []
        beit3_candidates_lists = []

        if "siglip" in model_choices:
            for vq in visual_queries:
                query_vector = self._embedding_service.get_siglip_embedding(vq)
                siglip_candidates_lists.append(self._siglip_repo.search(query_vector, fetch_k))
                
        if "beit3" in model_choices:
            for vq in visual_queries:
                query_vector = self._embedding_service.get_beit3_embedding(vq)
                beit3_candidates_lists.append(self._beit3_repo.search(query_vector, fetch_k))

        es_candidates = []
        if search_sources and getattr(search_sources, "asr", False):
            # ASR strictly uses original query
            es_candidates = self._text_repository.search_metadata(query, None, fetch_k)

        def add_to_srrf(cands: list['ScoredCandidate'], srrf_dict: dict[str, float], k=60):
            if not cands:
                return
            max_score = max(c.similarity_score for c in cands)
            min_score = min(c.similarity_score for c in cands)
            range_score = max_score - min_score if max_score > min_score else 1.0
            
            for rank, c in enumerate(cands, start=1):
                norm_score = (c.similarity_score - min_score) / range_score
                srrf_dict[c.image_path] = srrf_dict.get(c.image_path, 0.0) + norm_score / (k + rank)

        fused = {}
        siglip_raw = {}
        beit3_raw = {}
        es_raw = {}
        cmap = {}

        for cands in siglip_candidates_lists:
            add_to_srrf(cands, fused)
            for c in cands:
                siglip_raw[c.image_path] = max(siglip_raw.get(c.image_path, 0.0), c.similarity_score)
                cmap[c.image_path] = c
                
        for cands in beit3_candidates_lists:
            add_to_srrf(cands, fused)
            for c in cands:
                beit3_raw[c.image_path] = max(beit3_raw.get(c.image_path, 0.0), c.similarity_score)
                cmap[c.image_path] = c

        add_to_srrf(es_candidates, fused)
        for c in es_candidates:
            es_raw[c.image_path] = max(es_raw.get(c.image_path, 0.0), c.similarity_score)
            cmap[c.image_path] = c

        top_paths = sorted(fused.keys(), key=lambda x: fused[x], reverse=True)[:fetch_k]

        candidates = []
        for path in top_paths:
            c = cmap[path]
            candidates.append(c.model_copy(update={"similarity_score": fused[path]}))

        # 3. BLIP-2 Reranking
        if self._blip2_reranker.enable and use_reranking:
            candidates = self._blip2_reranker.rerank(query, candidates)

        return candidates

    def _retrieve_single(self, request: SearchRequest, enhanced_queries: list[str] | None = None) -> tuple[SingleSearchResult, ...]:
        model_choices = getattr(request, "model_choices", ["siglip", "beit3"])
        fetch_k = request.top_k * 5

        search_sources = getattr(request, "search_sources", None)

        candidates = self._search_candidates(request.query, model_choices, fetch_k, search_sources, enhanced_queries, getattr(request, "use_reranking", False))



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
                    image_path=keyframe.image_path,
                    segment_id=keyframe.segment_id or "",
                    asr_text=keyframe.asr_text or "",
                    ocr_text=keyframe.ocr_text or "",
                    objects=keyframe.objects or [],
                    similarity_score=candidate.similarity_score,
                    answer="",
                )
            )

        return tuple(results)

    def _retrieve_trake(self, request: TRAKESearchRequest, enhanced_queries: dict[int, list[str]] | None = None) -> tuple[TRAKESearchResult, ...]:
        if not request.events:
            return tuple()

        beam_width = 8
        max_kf_gap = getattr(request, "max_kf_gap", 200) # Defaults to 200 gap if not provided
        model_choices = getattr(request, "model_choices", ["siglip", "beit3"])

        # Stage 1: Get top-K for the first event
        search_sources = getattr(request, "search_sources", None)
        first_event = request.events[0]
        first_event_enhanced = enhanced_queries.get(first_event.event_index) if enhanced_queries else None
        
        # Since beam width is 8, fetch 100 candidates to start, then prune to beam_width
        first_candidates = self._search_candidates(first_event.query, model_choices, 100, search_sources, first_event_enhanced)

        if not first_candidates:
            return tuple()

        # beam = [(total_score, [(ScoredCandidate, s_i, lambda_i)])]
        beams: list[tuple[float, list[tuple[ScoredCandidate, float, float]]]] = [
            (c.similarity_score, [(c, c.similarity_score, 1.0)]) for c in first_candidates[:beam_width]
        ]

        # Stages 2..N
        for event in request.events[1:]:
            event_enhanced = enhanced_queries.get(event.event_index) if enhanced_queries else None
            candidates = self._search_candidates(event.query, model_choices, 200, search_sources, event_enhanced)
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

                    next_beams.append((total_score + c.similarity_score * decay, seq + [(c, c.similarity_score, decay)]))

            next_beams.sort(key=lambda x: x[0], reverse=True)
            beams = next_beams[:beam_width]

            if not beams:
                return tuple()

        # Stage 4: BLIP-2 Multiplicative Gating
        final_beams = []
        for total_score, seq in beams:
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
        for rank, (total_score, seq) in enumerate(final_beams[:request.top_k], start=1):
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
