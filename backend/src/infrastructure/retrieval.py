from typing import Protocol

from schemas.search import (
    SearchRequest,
    SingleSearchResult,
    TRAKESearchResult,
)


class RetrievalDataError(RuntimeError):
    """Raised when retrieval data violates its contract."""


class RetrievalEngine(Protocol):
    def retrieve(
        self, request: SearchRequest
    ) -> tuple[SingleSearchResult | TRAKESearchResult, ...]: ...
