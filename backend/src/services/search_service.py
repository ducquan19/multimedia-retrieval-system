from infrastructure.query_enhancer import QueryEnhancer
from infrastructure.retrieval import RetrievalEngine
from schemas.search import (
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
        max_query_length: int,
    ) -> None:
        self._retrieval_engine = retrieval_engine
        self._query_enhancer = query_enhancer
        self._max_trake_events = max_trake_events
        self._max_query_length = max_query_length

    def search(self, request: SearchRequest) -> SearchResponse:
        self._validate_query_lengths(request)
        if isinstance(request, TRAKESearchRequest) and len(request.events) > self._max_trake_events:
            raise SearchValidationError(
                f"TRAKE supports at most {self._max_trake_events} events in this deployment"
            )

        original_query = (
            request.main_query if isinstance(request, TRAKESearchRequest) else request.query
        )
        enhanced_queries = (
            self._query_enhancer.enhance(original_query, request.query_type)
            if request.enhance_query
            else None
        )
        
        enhanced_query_str = None
        if enhanced_queries:
            enhanced_query_str = "\n".join(f"- {q}" for q in enhanced_queries)
            
        model_choices = getattr(request, "model_choices", [])
        
        results = self._retrieval_engine.retrieve(request, enhanced_queries)

        if isinstance(request, KISSearchRequest):
            return KISSearchResponse(
                query_type="KIS",
                original_query=original_query,
                enhanced_query=enhanced_query_str,
                model_choices=model_choices,
                results=self._only_single_results(results),
            )
        if isinstance(request, VQASearchRequest):
            return VQASearchResponse(
                query_type="VQA",
                original_query=original_query,
                enhanced_query=enhanced_query_str,
                model_choices=model_choices,
                results=self._only_single_results(results),
            )
        return TRAKESearchResponse(
            query_type="TRAKE",
            original_query=original_query,
            enhanced_query=enhanced_query_str,
            model_choices=model_choices,
            results=self._only_trake_results(results),
        )

    def _validate_query_lengths(self, request: SearchRequest) -> None:
        if isinstance(request, TRAKESearchRequest):
            queries = (("main_query", request.main_query),) + tuple(
                (f"events[{event.event_index}].query", event.query) for event in request.events
            )
        else:
            queries = (("query", request.query),)

        for field_name, query in queries:
            if len(query) > self._max_query_length:
                raise SearchValidationError(
                    f"{field_name} must contain at most {self._max_query_length} characters"
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
