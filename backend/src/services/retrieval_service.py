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
    QueryVariants,
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
        self, request: SearchRequest, enhanced_queries: QueryVariants | dict[int, QueryVariants] | None = None
    ) -> tuple[SingleSearchResult | TRAKESearchResult, ...]:
        if isinstance(request, TRAKESearchRequest):
            return self._retrieve_trake(request, enhanced_queries)
        return self._retrieve_single(request, enhanced_queries)

    def _search_candidates(
        self, query: str, model_choices: list[str], fetch_k: int, search_sources=None, enhanced: QueryVariants | None = None, use_reranking: bool = False
    ) -> list[ScoredCandidate]:
        visual_queries = enhanced.variants if enhanced else [query]
        
        w_vis = enhanced.w_vis if enhanced else (1.0 if getattr(search_sources, "image", True) else 0.0)
        w_ocr = enhanced.w_ocr if enhanced else (1.0 if getattr(search_sources, "ocr", False) else 0.0)
        w_asr = enhanced.w_asr if enhanced else (1.0 if getattr(search_sources, "asr", False) else 0.0)

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

        asr_cands = []
        if search_sources and getattr(search_sources, "asr", False) and w_asr > 0:
            asr_cands = self._text_repository.search_text(query, ["asr_text"], None, fetch_k)

        ocr_cands = []
        if search_sources and getattr(search_sources, "ocr", False) and w_ocr > 0:
            ocr_cands = self._text_repository.search_text(query, ["ocr_text"], None, fetch_k)

        cmap = {}
        for cands in siglip_candidates_lists + beit3_candidates_lists + [asr_cands, ocr_cands]:
            for c in cands:
                if c.image_path not in cmap:
                    cmap[c.image_path] = c

        # 1. Visual SRRF (for fusing SigLIP and BEiT-3)
        vis_srrf = {}
        def add_to_srrf(cands: list['ScoredCandidate'], k=60):
            if not cands: return
            max_s = max(c.similarity_score for c in cands)
            min_s = min(c.similarity_score for c in cands)
            range_s = max_s - min_s if max_s > min_s else 1.0
            for rank, c in enumerate(cands, start=1):
                norm_score = (c.similarity_score - min_s) / range_s
                vis_srrf[c.image_path] = vis_srrf.get(c.image_path, 0.0) + norm_score / (k + rank)

        for cands in siglip_candidates_lists: add_to_srrf(cands)
        for cands in beit3_candidates_lists: add_to_srrf(cands)

        # 2. Min-Max Normalization
        def norm_dict(d: dict[str, float]) -> dict[str, float]:
            if not d: return {}
            max_s, min_s = max(d.values()), min(d.values())
            range_s = max_s - min_s + 1e-6
            return {k: (v - min_s) / range_s for k, v in d.items()}

        vis_norm = norm_dict(vis_srrf)
        asr_norm = norm_dict({c.image_path: c.similarity_score for c in asr_cands})
        ocr_norm = norm_dict({c.image_path: c.similarity_score for c in ocr_cands})

        # 3. Final Score Fusion
        final_scores = {}
        for p in cmap:
            final_scores[p] = (
                w_vis * vis_norm.get(p, 0.0) +
                w_asr * asr_norm.get(p, 0.0) +
                w_ocr * ocr_norm.get(p, 0.0)
            )

        top_paths = sorted(final_scores.keys(), key=lambda x: final_scores[x], reverse=True)[:fetch_k]
        candidates = [cmap[p].model_copy(update={"similarity_score": final_scores[p]}) for p in top_paths]

        if self._blip2_reranker.enable and use_reranking:
            candidates = self._blip2_reranker.rerank(query, candidates)

        return candidates

    def _retrieve_single(self, request: SearchRequest, enhanced_queries: QueryVariants | None = None) -> tuple[SingleSearchResult, ...]:
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

    def _retrieve_trake(self, request: TRAKESearchRequest, enhanced_queries: dict[int, QueryVariants] | None = None) -> tuple[TRAKESearchResult, ...]:
        if not request.events:
            return tuple()

        beam_width = max(150, request.top_k * 5)
        max_kf_gap = getattr(request, "max_kf_gap", 3000) # Defaults to 3000 gap if not provided
        model_choices = getattr(request, "model_choices", ["siglip", "beit3"])
        fetch_k = request.top_k * 10
        search_sources = getattr(request, "search_sources", None)
        use_reranking = getattr(request, "use_reranking", False)

        # 1. Forward Pass: Fetch candidates for all events using per-event enhanced queries
        first_event = request.events[0]
        enhanced_for_first = enhanced_queries.get(first_event.event_index) if enhanced_queries else None
        
        first_candidates = self._search_candidates(
            first_event.query, model_choices, fetch_k, search_sources, enhanced_for_first, use_reranking
        )

        if not first_candidates:
            return tuple()

        # beam = [(total_score, [(ScoredCandidate, s_i, lambda_i)])]
        beams: list[tuple[float, list[tuple[ScoredCandidate, float, float]]]] = [
            (c.similarity_score, [(c, c.similarity_score, 1.0)]) for c in first_candidates[:beam_width]
        ]

        # Stages 2..N
        for event in request.events[1:]:
            event_enhanced = enhanced_queries.get(event.event_index) if enhanced_queries else None
            candidates = self._search_candidates(event.query, model_choices, fetch_k, search_sources, event_enhanced)
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
