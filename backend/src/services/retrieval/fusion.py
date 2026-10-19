"""Hybrid candidate search: every enabled modality fetches candidates, then one fusion.

Fusion: each visual list is min-max normalized and accumulated as score / (60 + rank)
(score-weighted RRF), the visual total is min-max normalized again, ASR BM25 scores are divided
by the best hit and shared by every keyframe of a shot, object scores are already in [0, 1].
The modality weights are renormalized over the modalities that returned candidates.

A new source (e.g. OCR) is one more ``Modality``: it fetches its candidates and scores the
pooled candidates of all modalities; the fusion itself does not change.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from core.intro_exclusion import IntroExclusionPolicy
from core.timing import stage
from models.candidate import ScoredCandidate
from models.query import ObjectQueryTerm, QueryVariants, SearchSources
from repositories.text_repository import TextIndexMismatch, TextSearchUnavailable
from services.weights import ModalityWeights, object_terms_for, resolve_weights

_SRRF_K = 60
_ASR_OVERFETCH = 3
_MAX_ASR_FETCH = 10_000
ASR_UNAVAILABLE = "ASR search (Elasticsearch) is unavailable, so the ASR source was ignored."
ASR_INDEX_MISMATCH = (
    "The ASR index was built from another keyframes.json, so the ASR source was ignored. "
    "Rerun scripts/build_es_index.py."
)

# Pooled candidates of one search, by FAISS id
CandidatePool = dict[int, ScoredCandidate]


@dataclass(frozen=True, eq=False)
class FusionQuery:
    """What one candidate search asks of every modality."""

    query: str
    visual_queries: tuple[str, ...]
    asr_query: str
    object_terms: tuple[ObjectQueryTerm, ...]
    model_choices: tuple[str, ...]
    fetch_k: int
    # Boolean mask over FAISS ids that restricts every modality, or None
    allowed: np.ndarray | None


class ModalityHits(Protocol):
    @property
    def candidates(self) -> Sequence[ScoredCandidate]: ...

    def scores(self, pool: CandidatePool) -> dict[int, float]:
        """Score in [0, 1] of pooled candidates (missing ids count as 0)."""
        ...


class Modality(Protocol):
    def fetch(self, query: FusionQuery, warnings: list[str]) -> ModalityHits: ...


class VectorIndex(Protocol):
    def search(
        self, vector: np.ndarray, top_k: int, allowed: np.ndarray | None = None
    ) -> list[ScoredCandidate]: ...


class TextIndex(Protocol):
    def search_text(
        self, text_query: str, fields: list[str], top_k: int, allowed: np.ndarray | None = None
    ) -> list[ScoredCandidate]: ...


class ObjectIndex(Protocol):
    @property
    def available(self) -> bool: ...

    def search(
        self, terms: Sequence[ObjectQueryTerm], top_k: int, allowed: np.ndarray | None = None
    ) -> list[ScoredCandidate]: ...

    def score(self, keyframe_id: str, terms: Sequence[ObjectQueryTerm]) -> float: ...


class CandidateReranker(Protocol):
    @property
    def ready(self) -> bool: ...

    def rerank(self, query: str, candidates: list[ScoredCandidate]) -> list[ScoredCandidate]: ...


@dataclass(frozen=True)
class _VisualHits:
    lists: list[list[ScoredCandidate]]

    @property
    def candidates(self) -> list[ScoredCandidate]:
        return [candidate for candidates in self.lists for candidate in candidates]

    def scores(self, pool: CandidatePool) -> dict[int, float]:
        return _min_max(_score_weighted_rrf(self.lists))


class VisualModality:
    """Text-to-image search with every chosen model for every visual query variant."""

    def __init__(
        self,
        encoders: dict[str, Callable[[str], np.ndarray]],
        indexes: dict[str, VectorIndex],
        intro_exclusion_policy: IntroExclusionPolicy,
    ) -> None:
        self._encoders = encoders
        self._indexes = indexes
        self._intro_exclusion_policy = intro_exclusion_policy

    def fetch(self, query: FusionQuery, warnings: list[str]) -> _VisualHits:
        lists = []
        for model in self._indexes:
            if model not in query.model_choices:
                continue
            for text in query.visual_queries:
                with stage("embed"):
                    vector = self._encoders[model](text)
                with stage("faiss"):
                    candidates = self._indexes[model].search(vector, query.fetch_k, query.allowed)
                lists.append(self._intro_exclusion_policy.filter_candidates(candidates))
        return _VisualHits(lists)


@dataclass(frozen=True)
class _AsrHits:
    candidates: list[ScoredCandidate]

    def scores(self, pool: CandidatePool) -> dict[int, float]:
        # BM25 is divided by the best hit so the weakest hit still counts, and a shot's score is
        # shared by all its keyframes, including visual candidates ASR missed.
        by_segment: dict[str | int, float] = {}
        best = max((c.similarity_score for c in self.candidates), default=0.0)
        for c in self.candidates:
            segment = c.keyframe.segment_id or c.faiss_id
            score = c.similarity_score / best if best > 0 else 0.0
            by_segment[segment] = max(by_segment.get(segment, 0.0), score)
        return {
            faiss_id: by_segment.get(c.keyframe.segment_id or faiss_id, 0.0)
            for faiss_id, c in pool.items()
        }


class AsrModality:
    """BM25 over shot transcripts; an unavailable index only adds a warning."""

    def __init__(self, index: TextIndex, intro_exclusion_policy: IntroExclusionPolicy) -> None:
        self._index = index
        self._intro_exclusion_policy = intro_exclusion_policy

    def fetch(self, query: FusionQuery, warnings: list[str]) -> _AsrHits:
        candidates: list[ScoredCandidate] = []
        try:
            # Every keyframe of a shot shares its transcript, so over-fetch to cover more shots.
            with stage("asr"):
                candidates = self._index.search_text(
                    query.asr_query,
                    ["asr_text"],
                    min(query.fetch_k * _ASR_OVERFETCH, _MAX_ASR_FETCH),
                    query.allowed,
                )
        except TextIndexMismatch:
            warnings.append(ASR_INDEX_MISMATCH)
        except TextSearchUnavailable:
            warnings.append(ASR_UNAVAILABLE)
        return _AsrHits(self._intro_exclusion_policy.filter_candidates(candidates))


@dataclass(frozen=True)
class _ObjectHits:
    index: ObjectIndex
    terms: tuple[ObjectQueryTerm, ...]
    candidates: list[ScoredCandidate]

    def scores(self, pool: CandidatePool) -> dict[int, float]:
        # Object scores are already in [0, 1] and comparable across keyframes, so every pooled
        # candidate (not only the object top-k) is scored directly instead of normalized.
        return {
            faiss_id: self.index.score(c.keyframe.keyframe_id, self.terms)
            for faiss_id, c in pool.items()
        }


class ObjectModality:
    def __init__(self, index: ObjectIndex) -> None:
        self.index = index

    def fetch(self, query: FusionQuery, warnings: list[str]) -> _ObjectHits:
        with stage("object"):
            candidates = self.index.search(query.object_terms, query.fetch_k, query.allowed)
        return _ObjectHits(self.index, query.object_terms, candidates)


class CandidateSearch:
    """Fuses the candidates of the modalities a search enables into one ranked list."""

    def __init__(
        self,
        *,
        visual: VisualModality,
        asr: AsrModality,
        objects: ObjectModality | None,
        intro_exclusion_policy: IntroExclusionPolicy,
        reranker: CandidateReranker | None = None,
    ) -> None:
        # (weight name in ModalityWeights, modality), in the order candidates are pooled
        self._modalities: list[tuple[str, Modality]] = [("vis", visual), ("asr", asr)]
        if objects is not None:
            self._modalities.append(("obj", objects))
        self._objects = objects
        self._intro_exclusion_policy = intro_exclusion_policy
        self._reranker = reranker

    @property
    def object_search_available(self) -> bool:
        return self._objects is not None and self._objects.index.available

    @property
    def reranker_ready(self) -> bool:
        return self._reranker is not None and self._reranker.ready

    def search(
        self,
        query: str,
        model_choices: Sequence[str],
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
        """Fused candidates, best first; ``allowed`` restricts every modality."""
        object_terms = object_terms_for(
            sources, object_query, enhanced, self.object_search_available
        )
        weights = resolve_weights(sources, enhanced, object_query, object_terms)

        if not asr_query and enhanced and enhanced.asr_query_vi:
            # Spoken keywords sharpen BM25; the raw query keeps recall for paraphrases.
            asr_query = f"{enhanced.asr_query_vi} {query}"
        fusion_query = FusionQuery(
            query=query,
            visual_queries=tuple(enhanced.variants if enhanced else [query]),
            asr_query=asr_query or query,
            object_terms=object_terms,
            model_choices=tuple(model_choices),
            fetch_k=fetch_k,
            allowed=allowed,
        )
        hits = [
            (weight, modality.fetch(fusion_query, warnings))
            for name, modality in self._modalities
            if (weight := _weight(weights, name)) > 0
        ]

        with stage("fusion"):
            candidates = _fuse(hits, fetch_k)

        if rerank and self.reranker_ready:
            with stage("rerank"):
                candidates = self._reranker.rerank(query, candidates)

        # Repository-level filters protect recall; this is a final invariant check before any
        # caller performs ranking or temporal reasoning.
        return self._intro_exclusion_policy.filter_candidates(candidates)


def _weight(weights: ModalityWeights, name: str) -> float:
    return getattr(weights, name)


def fuse_visual_lists(lists: list[list[ScoredCandidate]]) -> list[ScoredCandidate]:
    """One ranked list from several visual lists; a single list keeps its own scores."""
    if len(lists) == 1:
        return lists[0]
    hits = _VisualHits(lists)
    pool: CandidatePool = {}
    for candidate in hits.candidates:
        pool.setdefault(candidate.faiss_id, candidate)
    scores = hits.scores(pool)
    ranked = sorted(pool, key=lambda faiss_id: scores.get(faiss_id, 0.0), reverse=True)
    return [pool[faiss_id].with_score(scores.get(faiss_id, 0.0)) for faiss_id in ranked]


def _fuse(hits: list[tuple[float, ModalityHits]], fetch_k: int) -> list[ScoredCandidate]:
    pool: CandidatePool = {}
    for _, modality_hits in hits:
        for candidate in modality_hits.candidates:
            pool.setdefault(candidate.faiss_id, candidate)

    # Weights are renormalized over modalities that returned candidates, so an empty modality
    # (e.g. ES offline) does not flatten the scores.
    active = [(weight, h.scores(pool)) for weight, h in hits if h.candidates]
    weight_sum = sum(weight for weight, _ in active) or 1.0
    final_scores = {
        faiss_id: sum(weight * scores.get(faiss_id, 0.0) for weight, scores in active) / weight_sum
        for faiss_id in pool
    }
    top_ids = sorted(final_scores, key=final_scores.__getitem__, reverse=True)[:fetch_k]
    return [pool[faiss_id].with_score(final_scores[faiss_id]) for faiss_id in top_ids]


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
