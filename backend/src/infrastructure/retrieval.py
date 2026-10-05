from dataclasses import dataclass
from typing import Protocol

from schemas.search import (
    KISQueryPlan,
    QueryVariants,
    SearchRequest,
    SingleSearchResult,
    TRAKESearchResult,
)


class RetrievalDataError(RuntimeError):
    """Raised when retrieval data or a model is missing, misaligned or corrupted."""


@dataclass(frozen=True)
class RetrievalOutcome:
    results: tuple[SingleSearchResult | TRAKESearchResult, ...]
    # Degradations the user should know about, e.g. a modality that could not be searched.
    warnings: tuple[str, ...] = ()


EnhancedQueries = QueryVariants | dict[int, QueryVariants] | KISQueryPlan | None


class RetrievalEngine(Protocol):
    """Protocol for abstracting the concrete retrieval service from domain logic."""

    def retrieve(
        self, request: SearchRequest, enhanced_queries: EnhancedQueries = None
    ) -> RetrievalOutcome: ...
