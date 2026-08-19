from typing import Protocol

from schemas.search import (
    SearchRequest,
    SingleSearchResult,
    TRAKESearchResult,
)


class RetrievalDataError(RuntimeError):
    """Raised when retrieval data violates its contract."""


class RetrievalEngine(Protocol):
    """Protocol for abstracting the concrete retrieval service from domain logic."""

    def retrieve(self, request: SearchRequest, enhanced_queries: list[str] | dict[int, list[str]] | None = None) -> tuple[SingleSearchResult | TRAKESearchResult, ...]: ...
