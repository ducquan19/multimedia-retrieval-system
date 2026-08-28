from pathlib import Path

from infrastructure.query_enhancer import QueryEnhancer
from infrastructure.retrieval import RetrievalEngine
from schemas.search import (
    KISQueryPlan,
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
        data_root: Path,
    ) -> None:
        self._retrieval_engine = retrieval_engine
        self._query_enhancer = query_enhancer
        self._max_trake_events = max_trake_events
        self._max_query_length = max_query_length
        self._data_root = data_root

    def plan_kis(self, query: str) -> KISQueryPlan:
        if len(query) > self._max_query_length:
            raise SearchValidationError(
                f"query must contain at most {self._max_query_length} characters"
            )
        plan = self._query_enhancer.plan_kis(query)
        if plan is None:
            raise SearchValidationError(
                "Gemini could not create a KIS query plan. Check the API key/quota and retry."
            )
        return plan

    def search(self, request: SearchRequest) -> SearchResponse:
        self._validate_query_lengths(request)
        if isinstance(request, TRAKESearchRequest) and len(request.events) > self._max_trake_events:
            raise SearchValidationError(
                f"TRAKE supports at most {self._max_trake_events} events in this deployment"
            )

        warnings = []
        applied_weights = None
        search_sources = getattr(request, "search_sources", None)
        default_w_vis = 1.0 if getattr(search_sources, "image", True) else 0.0
        default_w_asr = 1.0 if getattr(search_sources, "asr", False) else 0.0

        query_plan = request.query_plan if isinstance(request, KISSearchRequest) else None

        if isinstance(request, TRAKESearchRequest):
            original_query = request.main_query
            if request.enhance_query:
                queries_dict = {event.event_index: event.query for event in request.events}
                enhanced_queries = self._query_enhancer.enhance_batch(queries_dict)
                if not enhanced_queries:
                    warnings.append(
                        "Gemini API quota exceeded or failed. Falling back to original "
                        "queries with default weights."
                    )
                    enhanced_queries = None
                    enhanced_query_str = None
                    applied_weights = {
                        "w_vis": default_w_vis,
                        "w_asr": default_w_asr,
                    }
                else:
                    enhanced_query_str = "\n".join(
                        f"Event {k}: {v.variants[0] if v and v.variants else ''}"
                        for k, v in enhanced_queries.items()
                    )
                    first_v = next(iter(enhanced_queries.values()), None)
                    if first_v:
                        applied_weights = {
                            "w_vis": first_v.w_vis,
                            "w_asr": first_v.w_asr,
                        }
            else:
                enhanced_queries = None
                enhanced_query_str = None
        elif isinstance(request, KISSearchRequest) and request.query_understanding:
            original_query = request.query
            enhanced_queries = query_plan
            enhanced_query_str = None
            warnings.extend(query_plan.warnings)
        else:
            original_query = request.query
            if request.enhance_query:
                enhanced_queries = self._query_enhancer.enhance(original_query, request.query_type)
                if enhanced_queries and enhanced_queries.variants:
                    enhanced_query_str = f"- {enhanced_queries.variants[0]}"
                    applied_weights = {
                        "w_vis": enhanced_queries.w_vis,
                        "w_asr": enhanced_queries.w_asr,
                    }
                else:
                    warnings.append(
                        "Gemini API quota exceeded or failed. Falling back to original "
                        "query with default weights."
                    )
                    enhanced_query_str = None
                    enhanced_queries = None
                    applied_weights = {
                        "w_vis": default_w_vis,
                        "w_asr": default_w_asr,
                    }
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
                applied_weights=applied_weights,
                warnings=warnings,
                query_plan=query_plan,
                results=self._only_single_results(results),
            )
        if isinstance(request, VQASearchRequest):
            return VQASearchResponse(
                query_type="VQA",
                original_query=original_query,
                enhanced_query=enhanced_query_str,
                model_choices=model_choices,
                applied_weights=applied_weights,
                warnings=warnings,
                results=self._only_single_results(results),
            )
        return TRAKESearchResponse(
            query_type="TRAKE",
            original_query=original_query,
            enhanced_query=enhanced_query_str,
            model_choices=model_choices,
            applied_weights=applied_weights,
            warnings=warnings,
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
