"""Interfaces the search services depend on; the adapters implement them structurally.

SearchService only sees these protocols, so tests (and alternative implementations) can
replace the retrieval engine or the LLM query enhancer without touching it.
"""

from dataclasses import dataclass
from typing import Protocol

from models.query import KISQueryPlan, QueryVariants, SearchSources
from schemas.search import (
    SearchRequest,
    SimilarSearchRequest,
    SimilarSearchResponse,
    SingleSearchResult,
    TRAKESearchResult,
)


@dataclass(frozen=True)
class RetrievalOutcome:
    results: tuple[SingleSearchResult | TRAKESearchResult, ...]
    # Degradations the user should know about, e.g. a modality that could not be searched.
    warnings: tuple[str, ...] = ()
    # TRAFFIC only: how many keyframes the metadata filters left to search
    filtered_keyframes: int | None = None


EnhancedQueries = QueryVariants | dict[int, QueryVariants] | KISQueryPlan | None


class RetrievalEngine(Protocol):
    def retrieve(
        self, request: SearchRequest, enhanced_queries: EnhancedQueries = None
    ) -> RetrievalOutcome: ...

    def similar(self, request: SimilarSearchRequest) -> SimilarSearchResponse: ...


class QueryEnhancer(Protocol):
    """Rewrites queries and plans KIS searches (Gemini in production); None means fall back."""

    def enhance(
        self, query: str, query_type: str, sources: SearchSources | None = None
    ) -> QueryVariants | None: ...
    def enhance_batch(
        self, queries: dict[int, str], sources: SearchSources | None = None
    ) -> dict[int, QueryVariants] | None: ...
    def plan_kis(self, query: str) -> KISQueryPlan | None: ...
