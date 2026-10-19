from core.timing import stage
from repositories.object_repository import KeyframeObjectRepository
from schemas.search import (
    KISQueryPlan,
    KISSearchRequest,
    KISSearchResponse,
    ObjectQueryTerm,
    QueryVariants,
    SearchRequest,
    SearchResponse,
    SimilarSearchRequest,
    SimilarSearchResponse,
    SingleSearchResult,
    TrafficSearchRequest,
    TrafficSearchResponse,
    TRAKESearchRequest,
    TRAKESearchResponse,
    TRAKESearchResult,
    VQASearchResponse,
)
from services.ports import EnhancedQueries, QueryEnhancer, RetrievalEngine
from services.weights import object_terms_for, resolve_weights

_GEMINI_FALLBACK_WARNING = (
    "Gemini API quota exceeded or failed. Falling back to the original {what} with default weights."
)


class SearchValidationError(ValueError):
    """Raised when runtime-configured search constraints are violated."""


class SearchService:
    def __init__(
        self,
        retrieval_engine: RetrievalEngine,
        query_enhancer: QueryEnhancer | None,
        max_trake_events: int,
        max_query_length: int,
        object_repository: KeyframeObjectRepository | None = None,
    ) -> None:
        self._retrieval_engine = retrieval_engine
        self._query_enhancer = query_enhancer
        self._max_trake_events = max_trake_events
        self._max_query_length = max_query_length
        self._object_repository = object_repository

    @property
    def _object_search_available(self) -> bool:
        return self._object_repository is not None and self._object_repository.available

    def plan_kis(self, query: str) -> KISQueryPlan:
        if len(query) > self._max_query_length:
            raise SearchValidationError(
                f"query must contain at most {self._max_query_length} characters"
            )
        with stage("gemini"):
            plan = self._query_enhancer.plan_kis(query) if self._query_enhancer else None
        if plan is None:
            raise SearchValidationError(
                "Gemini could not create a KIS query plan. Check the API key/quota and retry."
            )
        return plan

    def similar(self, request: SimilarSearchRequest) -> SimilarSearchResponse:
        return self._retrieval_engine.similar(request)

    def search(self, request: SearchRequest) -> SearchResponse:
        self._validate_query_lengths(request)
        if isinstance(request, TRAKESearchRequest) and len(request.events) > self._max_trake_events:
            raise SearchValidationError(
                f"TRAKE supports at most {self._max_trake_events} events in this deployment"
            )
        planned = isinstance(request, KISSearchRequest) and request.query_understanding
        self._validate_object_query(request, planned)

        warnings: list[str] = []
        applied_weights: dict[str, float] | None = None
        auto_objects: tuple[ObjectQueryTerm, ...] = ()
        enhanced_query_str: str | None = None
        enhanced_queries: EnhancedQueries = None
        query_plan = request.query_plan if isinstance(request, KISSearchRequest) else None

        if isinstance(request, TRAKESearchRequest):
            original_query = request.main_query
            if request.enhance_query:
                batch = self._enhance_batch(request)
                if batch:
                    enhanced_queries = batch
                    enhanced_query_str = "\n".join(
                        f"Event {index}: {self._describe_enhanced(variants, request)}"
                        for index, variants in sorted(batch.items())
                    )
                    first = batch.get(request.events[0].event_index)
                    if first:
                        applied_weights = self._applied_weights(request, first)
                    auto_objects = tuple(term for v in batch.values() for term in v.objects)
                else:
                    warnings.append(_GEMINI_FALLBACK_WARNING.format(what="queries"))
                    applied_weights = self._applied_weights(request, None)
        elif planned:
            original_query = request.query
            enhanced_queries = query_plan
            warnings.extend(query_plan.warnings)
        else:
            original_query = request.query
            if request.enhance_query:
                enhanced = self._enhance(request)
                if enhanced is not None:
                    enhanced_queries = enhanced
                    enhanced_query_str = f"- {self._describe_enhanced(enhanced, request)}"
                    applied_weights = self._applied_weights(request, enhanced)
                    auto_objects = enhanced.objects
                else:
                    warnings.append(_GEMINI_FALLBACK_WARNING.format(what="query"))
                    applied_weights = self._applied_weights(request, None)

        if not planned:
            warnings.extend(self._object_warnings(request, auto_objects))

        outcome = self._retrieval_engine.retrieve(request, enhanced_queries)
        warnings.extend(outcome.warnings)

        common = {
            "original_query": original_query,
            "enhanced_query": enhanced_query_str,
            "model_choices": request.model_choices,
            "applied_weights": applied_weights,
            "warnings": warnings,
        }
        if isinstance(request, TRAKESearchRequest):
            return TRAKESearchResponse(
                query_type="TRAKE", results=self._only_trake_results(outcome.results), **common
            )
        results = self._only_single_results(outcome.results)
        if isinstance(request, KISSearchRequest):
            return KISSearchResponse(
                query_type="KIS",
                query_plan=query_plan,
                auto_object_query=auto_objects,
                results=results,
                **common,
            )
        if isinstance(request, TrafficSearchRequest):
            return TrafficSearchResponse(
                query_type="TRAFFIC",
                auto_object_query=auto_objects,
                filtered_keyframes=outcome.filtered_keyframes or 0,
                results=results,
                **common,
            )
        return VQASearchResponse(
            query_type="VQA", auto_object_query=auto_objects, results=results, **common
        )

    def _enhance(self, request: SearchRequest) -> QueryVariants | None:
        if self._query_enhancer is None:
            return None
        with stage("gemini"):
            enhanced = self._query_enhancer.enhance(
                request.query, request.query_type, request.search_sources
            )
        return enhanced if enhanced and enhanced.variants else None

    def _enhance_batch(self, request: TRAKESearchRequest) -> dict[int, QueryVariants] | None:
        if self._query_enhancer is None:
            return None
        queries = {event.event_index: event.query for event in request.events}
        with stage("gemini"):
            return self._query_enhancer.enhance_batch(queries, request.search_sources) or None

    def _applied_weights(
        self, request: SearchRequest, enhanced: QueryVariants | None
    ) -> dict[str, float]:
        """The weights the retrieval engine fuses with (see services.weights)."""
        object_terms = object_terms_for(
            request.search_sources, request.object_query, enhanced, self._object_search_available
        )
        return resolve_weights(
            request.search_sources, enhanced, request.object_query, object_terms
        ).as_dict()

    @staticmethod
    def _validate_object_query(request: SearchRequest, planned: bool) -> None:
        if planned or not request.search_sources.object or request.object_query:
            return
        if not request.enhance_query:
            raise SearchValidationError(
                "object_query must contain at least one object when the Object source is "
                "enabled, unless Enhance query picks the objects automatically"
            )

    @staticmethod
    def _describe_enhanced(enhanced: QueryVariants, request: SearchRequest) -> str:
        parts = [enhanced.variants[0]]
        if request.search_sources.asr and enhanced.asr_query_vi:
            parts.append(f"ASR: {enhanced.asr_query_vi}")
        if request.search_sources.object and enhanced.objects:
            parts.append(
                "Objects: "
                + ", ".join(f"{term.label} ≥{term.min_count}" for term in enhanced.objects)
            )
        return " | ".join(parts)

    def _object_warnings(
        self, request: SearchRequest, auto_objects: tuple[ObjectQueryTerm, ...]
    ) -> list[str]:
        if not request.search_sources.object:
            return []
        if not self._object_search_available:
            return [
                "Object index is unavailable, so the Object source was ignored. "
                "Run scripts/build_object_index.py."
            ]
        warnings = []
        unknown = self._object_repository.unknown_labels(request.object_query)
        if unknown:
            warnings.append(f"Unknown object labels were ignored: {', '.join(unknown)}")
        if request.enhance_query and not request.object_query and not auto_objects:
            warnings.append("Gemini found no detectable objects in the query.")
        return warnings

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
        return tuple(results)  # type: ignore[arg-type]

    @staticmethod
    def _only_trake_results(
        results: tuple[SingleSearchResult | TRAKESearchResult, ...],
    ) -> tuple[TRAKESearchResult, ...]:
        if not all(isinstance(result, TRAKESearchResult) for result in results):
            raise TypeError("Retrieval engine returned single-frame results for TRAKE")
        return tuple(results)  # type: ignore[arg-type]
