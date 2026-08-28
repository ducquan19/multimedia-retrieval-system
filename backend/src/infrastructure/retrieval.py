from typing import Protocol

from schemas.search import (
    KISQueryPlan,
    QueryVariants,
    SearchRequest,
    SingleSearchResult,
    TRAKESearchResult,
)


class RetrievalDataError(RuntimeError):
    """Raised when retrieval data violates its contract."""


class RetrievalEngine(Protocol):
    """Protocol for abstracting the concrete retrieval service from domain logic."""

    def retrieve(
        self,
        request: SearchRequest,
        enhanced_queries: QueryVariants | dict[int, QueryVariants] | KISQueryPlan | None = None,
    ) -> tuple[SingleSearchResult | TRAKESearchResult, ...]: ...
