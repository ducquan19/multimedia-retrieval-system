from aic_app.adapters.query_enhancer import QueryEnhancer
from aic_app.adapters.retrieval import RetrievalEngine
from aic_app.domain.search import (
    KISSearchRequest,
    KISSearchResponse,
    SearchRequest,
    SearchResponse,
    SingleSearchResult,
    TRAKESearchRequest,
    TRAKESearchResponse,
    TRAKESearchResult,
    VQASearchRequest,
    VQASearchResponse,
)


class SearchValidationError(ValueError):
    """Raised when runtime-configured search constraints are violated."""


class SearchService:
    def __init__(
        self,
        retrieval_engine: RetrievalEngine,
        query_enhancer: QueryEnhancer,
        max_trake_events: int,
    ) -> None:
        self._retrieval_engine = retrieval_engine
        self._query_enhancer = query_enhancer
        self._max_trake_events = max_trake_events

    def search(self, request: SearchRequest) -> SearchResponse:
        if isinstance(request, TRAKESearchRequest) and len(request.events) > self._max_trake_events:
            raise SearchValidationError(
                f"TRAKE supports at most {self._max_trake_events} events in this deployment"
            )

        original_query = (
            request.main_query if isinstance(request, TRAKESearchRequest) else request.query
        )
        enhanced_query = (
            self._query_enhancer.enhance(original_query, request.query_type)
            if request.enhance_query
            else None
        )
        results = self._retrieval_engine.retrieve(request)

        if isinstance(request, KISSearchRequest):
            return KISSearchResponse(
                query_type="KIS",
                original_query=original_query,
                enhanced_query=enhanced_query,
                results=self._only_single_results(results),
            )
        if isinstance(request, VQASearchRequest):
            return VQASearchResponse(
                query_type="VQA",
                original_query=original_query,
                enhanced_query=enhanced_query,
                results=self._only_single_results(results),
            )
        return TRAKESearchResponse(
            query_type="TRAKE",
            original_query=original_query,
            enhanced_query=enhanced_query,
            results=self._only_trake_results(results),
        )

    @staticmethod
    def _only_single_results(
        results: tuple[SingleSearchResult | TRAKESearchResult, ...],
    ) -> tuple[SingleSearchResult, ...]:
        if not all(isinstance(result, SingleSearchResult) for result in results):
            raise TypeError("Retrieval engine returned TRAKE results for a single-frame query")
        return tuple(result for result in results if isinstance(result, SingleSearchResult))

    @staticmethod
    def _only_trake_results(
        results: tuple[SingleSearchResult | TRAKESearchResult, ...],
    ) -> tuple[TRAKESearchResult, ...]:
        if not all(isinstance(result, TRAKESearchResult) for result in results):
            raise TypeError("Retrieval engine returned single-frame results for TRAKE")
        return tuple(result for result in results if isinstance(result, TRAKESearchResult))
