from pathlib import Path

from core.constants import MANUAL_OBJECT_WEIGHT
from infrastructure.query_enhancer import QueryEnhancer
from infrastructure.retrieval import RetrievalEngine
from repositories.object_repository import KeyframeObjectRepository
from repositories.traffic_repository import TrafficMetadataRepository
from schemas.search import (
    KISQueryPlan,
    KISSearchRequest,
    KISSearchResponse,
    ObjectQueryTerm,
    QueryVariants,
    SearchRequest,
    SearchResponse,
    SingleSearchResult,
    TRAKESearchRequest,
    TRAKESearchResponse,
    TRAKESearchResult,
    TrafficSearchRequest,
    TrafficSearchResponse,
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
        object_repository: KeyframeObjectRepository | None = None,
        traffic_repository: TrafficMetadataRepository | None = None,
    ) -> None:
        self._retrieval_engine = retrieval_engine
        self._query_enhancer = query_enhancer
        self._max_trake_events = max_trake_events
        self._max_query_length = max_query_length
        self._data_root = data_root
        self._object_repository = object_repository
        self._traffic_repository = traffic_repository

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

        warnings: list[str] = []
        applied_weights = None
        auto_objects: tuple[ObjectQueryTerm, ...] = ()
        sources = request.search_sources
        default_weights = {
            "w_vis": 1.0 if sources.image else 0.0,
            "w_asr": 1.0 if sources.asr else 0.0,
            "w_obj": 1.0 if sources.object and request.object_query else 0.0,
        }

        query_plan = request.query_plan if isinstance(request, KISSearchRequest) else None
        planned = isinstance(request, KISSearchRequest) and request.query_understanding
        self._validate_object_query(request, planned)

        if isinstance(request, TRAKESearchRequest):
            original_query = request.main_query
            if request.enhance_query:
                queries_dict = {event.event_index: event.query for event in request.events}
                enhanced_queries = self._query_enhancer.enhance_batch(queries_dict, sources)
                if not enhanced_queries:
                    warnings.append(
                        "Gemini API quota exceeded or failed. Falling back to original "
                        "queries with default weights."
                    )
                    enhanced_queries = None
                    enhanced_query_str = None
                    applied_weights = default_weights
                else:
                    enhanced_query_str = "\n".join(
                        f"Event {k}: {self._describe_enhanced(v, request)}"
                        for k, v in sorted(enhanced_queries.items())
                    )
                    first_v = enhanced_queries.get(request.events[0].event_index)
                    if first_v:
                        applied_weights = self._effective_weights(first_v, request)
                    auto_objects = tuple(
                        term for v in enhanced_queries.values() for term in v.objects
                    )
            else:
                enhanced_queries = None
                enhanced_query_str = None
        elif planned:
            original_query = request.query
            enhanced_queries = query_plan
            enhanced_query_str = None
            warnings.extend(query_plan.warnings)
        else:
            original_query = request.query
            if request.enhance_query:
                enhanced_queries = self._query_enhancer.enhance(
                    original_query, request.query_type, sources
                )
                if enhanced_queries and enhanced_queries.variants:
                    enhanced_query_str = f"- {self._describe_enhanced(enhanced_queries, request)}"
                    applied_weights = self._effective_weights(enhanced_queries, request)
                    auto_objects = enhanced_queries.objects
                else:
                    warnings.append(
                        "Gemini API quota exceeded or failed. Falling back to original "
                        "query with default weights."
                    )
                    enhanced_query_str = None
                    enhanced_queries = None
                    applied_weights = default_weights
            else:
                enhanced_queries = None
                enhanced_query_str = None

        if not planned:
            warnings.extend(self._object_warnings(request, auto_objects))

        model_choices = getattr(request, "model_choices", [])

        filtered_keyframes = 0
        if isinstance(request, TrafficSearchRequest):
            if self._traffic_repository is None or not self._traffic_repository.available:
                raise SearchValidationError(
                    "Traffic metadata is unavailable (data/traffic_camera/cameras.json)."
                )
            filtered_keyframes = int(self._traffic_repository.allowed_ids(request.filters).size)
            if filtered_keyframes == 0:
                warnings.append("No traffic keyframe matches the selected filters.")

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
                auto_object_query=auto_objects,
                results=self._only_single_results(results),
            )
        if isinstance(request, TrafficSearchRequest):
            return TrafficSearchResponse(
                query_type="TRAFFIC",
                original_query=original_query,
                enhanced_query=enhanced_query_str,
                model_choices=model_choices,
                applied_weights=applied_weights,
                warnings=warnings,
                auto_object_query=auto_objects,
                filtered_keyframes=filtered_keyframes,
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
                auto_object_query=auto_objects,
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
    def _effective_weights(enhanced: QueryVariants, request: SearchRequest) -> dict[str, float]:
        """Gemini weights gated by the enabled sources, as the retrieval engine applies them."""
        sources = request.search_sources
        w_obj = enhanced.w_obj if enhanced.objects else 0.0
        if request.object_query:
            w_obj = max(w_obj, MANUAL_OBJECT_WEIGHT)
        return {
            "w_vis": enhanced.w_vis if sources.image else 0.0,
            "w_asr": enhanced.w_asr if sources.asr else 0.0,
            "w_obj": w_obj if sources.object else 0.0,
        }

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
        if self._object_repository is None or not self._object_repository.available:
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
        return tuple(result for result in results if isinstance(result, SingleSearchResult))

    @staticmethod
    def _only_trake_results(
        results: tuple[SingleSearchResult | TRAKESearchResult, ...],
    ) -> tuple[TRAKESearchResult, ...]:
        if not all(isinstance(result, TRAKESearchResult) for result in results):
            raise TypeError("Retrieval engine returned single-frame results for TRAKE")
        return tuple(result for result in results if isinstance(result, TRAKESearchResult))
