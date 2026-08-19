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


from pathlib import Path

class SearchValidationError(ValueError):
    """Raised when runtime-configured search constraints are violated."""


class SearchService:
    def __init__(
        self,
        retrieval_engine: RetrievalEngine,
        query_enhancer: QueryEnhancer,
        max_trake_events: int,
        max_query_length: int,
        data_root: Path,
    ) -> None:
        self._retrieval_engine = retrieval_engine
        self._query_enhancer = query_enhancer
        self._max_trake_events = max_trake_events
        self._max_query_length = max_query_length
        self._data_root = data_root

    def search(self, request: SearchRequest) -> SearchResponse:
        self._validate_query_lengths(request)
        if isinstance(request, TRAKESearchRequest) and len(request.events) > self._max_trake_events:
            raise SearchValidationError(
                f"TRAKE supports at most {self._max_trake_events} events in this deployment"
            )

        if isinstance(request, TRAKESearchRequest):
            original_query = request.main_query
            if request.enhance_query:
                enhanced_queries = {
                    event.event_index: self._query_enhancer.enhance(event.query, request.query_type)
                    for event in request.events
                }
                # For display in response, we'll just show the first event's enhanced queries
                enhanced_query_str = "\n".join(f"Event {k}: {v[0] if v else ''}" for k, v in enhanced_queries.items())
            else:
                enhanced_queries = None
                enhanced_query_str = None
        else:
            original_query = request.query
            if request.enhance_query:
                enhanced_queries = self._query_enhancer.enhance(original_query, request.query_type)
                enhanced_query_str = "\n".join(f"- {q}" for q in enhanced_queries) if enhanced_queries else None
            else:
                enhanced_queries = None
                enhanced_query_str = None
            
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
            single_results = self._only_single_results(results)
            
            # Answer the question using the top result
            if single_results and self._query_enhancer and hasattr(self._query_enhancer, "answer_vqa"):
                top_result = single_results[0]
                answer = self._query_enhancer.answer_vqa(original_query, self._data_root / top_result.image_path)
                
                # Replace the top result with the answered one
                answered_top_result = top_result.model_copy(update={"answer": answer})
                single_results = (answered_top_result,) + single_results[1:]
                
            return VQASearchResponse(
                query_type="VQA",
                original_query=original_query,
                enhanced_query=enhanced_query_str,
                model_choices=model_choices,
                results=single_results,
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
            if query is not None and len(query) > self._max_query_length:
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
