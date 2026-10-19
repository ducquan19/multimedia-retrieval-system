"""Request and response models of the HTTP API.

The query value objects they are built from live in models/query.py and are re-exported here,
so API code can import every request type from one place.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.constants import DEFAULT_TOP_K, MAX_TOP_K, MIN_TOP_K
from models.query import (
    Daypart,
    KISQueryPlan,
    KISQueryPlanEvent,
    ObjectQueryTerm,
    QueryText,
    QueryVariants,
    SearchSources,
    TrafficFilters,
    Weather,
)

__all__ = [
    "KISQueryPlan",
    "KISQueryPlanEvent",
    "ObjectQueryTerm",
    "QueryText",
    "QueryVariants",
    "SearchSources",
    "TrafficFilters",
]


class KISQueryPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: QueryText


class BaseSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    top_k: int = Field(default=DEFAULT_TOP_K, ge=MIN_TOP_K, le=MAX_TOP_K)
    enhance_query: bool = False
    use_reranking: bool = False
    search_sources: SearchSources = Field(default_factory=SearchSources)
    model_choices: list[Literal["siglip", "beit3"]] = Field(default_factory=lambda: ["siglip"])
    object_query: tuple[ObjectQueryTerm, ...] = Field(default=(), max_length=10)


class KISSearchRequest(BaseSearchRequest):
    query_type: Literal["KIS"]
    query: QueryText
    query_understanding: bool = False
    query_plan: KISQueryPlan | None = None
    # Traffic-camera videos (N) have their own TRAFFIC tab, so KIS leaves them out by default.
    include_traffic: bool = False

    @model_validator(mode="after")
    def validate_query_understanding(self) -> "KISSearchRequest":
        if self.query_understanding and self.query_plan is None:
            raise ValueError("query_plan is required when query_understanding is enabled")
        if not self.query_understanding and self.query_plan is not None:
            raise ValueError("query_understanding must be enabled when query_plan is provided")
        if self.query_understanding and self.enhance_query:
            raise ValueError("enhance_query and query_understanding cannot be enabled together")
        return self


class VQASearchRequest(BaseSearchRequest):
    query_type: Literal["VQA"]
    query: QueryText


class TRAKEEventQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_index: int = Field(ge=1)
    query: QueryText


class TRAKESearchRequest(BaseSearchRequest):
    query_type: Literal["TRAKE"]
    main_query: str | None = None
    events: tuple[TRAKEEventQuery, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_event_indices(self) -> "TRAKESearchRequest":
        expected = list(range(1, len(self.events) + 1))
        actual = [event.event_index for event in self.events]
        if actual != expected:
            raise ValueError("TRAKE event_index values must be continuous from 1")
        return self


class TrafficSearchRequest(BaseSearchRequest):
    """Single-frame search restricted to the traffic-camera videos (N)."""

    query_type: Literal["TRAFFIC"]
    query: QueryText
    filters: TrafficFilters = Field(default_factory=TrafficFilters)


SearchRequest = Annotated[
    KISSearchRequest | VQASearchRequest | TRAKESearchRequest | TrafficSearchRequest,
    Field(discriminator="query_type"),
]


class SingleSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str
    rank: int = Field(ge=1)
    video_id: str
    frame_id: int = Field(ge=0)
    keyframe_url: str
    image_path: str
    segment_id: str
    asr_text: str
    objects: list[dict[str, Any]]
    similarity_score: float
    answer: str = ""
    # Original presentation time of the frame (ms) for VFR videos; None -> frame_id / fps.
    time_ms: int | None = None
    camera_name: str | None = None
    clock_time: str | None = None
    weather: str | None = None


class TRAKEEventResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_index: int = Field(ge=1)
    frame_id: int = Field(ge=0)
    keyframe_url: str
    segment_id: str
    asr_text: str
    objects: list[dict[str, Any]]
    similarity_score: float


class TRAKESearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str
    rank: int = Field(ge=1)
    video_id: str
    similarity_score: float
    events: tuple[TRAKEEventResult, ...]


class SimilarSearchRequest(BaseModel):
    """Query by example: keyframes that look like one keyframe, by its indexed embedding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    video_id: str = Field(min_length=1, max_length=128)
    frame_id: int = Field(ge=0)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=MIN_TOP_K, le=MAX_TOP_K)
    model_choices: list[Literal["siglip", "beit3"]] = Field(
        default_factory=lambda: ["siglip"], min_length=1
    )
    # The traffic videos (N) are left out unless the example is one of them or this is set.
    include_traffic: bool = False


class SimilarSearchResponse(BaseModel):
    query_type: Literal["SIMILAR"]
    video_id: str
    frame_id: int
    model_choices: list[str]
    warnings: list[str] = Field(default_factory=list)
    results: tuple[SingleSearchResult, ...]


class AppliedWeights(BaseModel):
    """The modality weights the fusion actually used (see services.weights)."""

    w_vis: float
    w_asr: float
    w_obj: float


class KISSearchResponse(BaseModel):
    query_type: Literal["KIS"]
    original_query: str
    enhanced_query: str | None
    model_choices: list[str] = Field(default_factory=list)
    applied_weights: AppliedWeights | None = None
    warnings: list[str] = Field(default_factory=list)
    query_plan: KISQueryPlan | None = None
    auto_object_query: tuple[ObjectQueryTerm, ...] = ()
    results: tuple[SingleSearchResult, ...]


class VQASearchResponse(BaseModel):
    query_type: Literal["VQA"]
    original_query: str
    enhanced_query: str | None
    model_choices: list[str] = Field(default_factory=list)
    applied_weights: AppliedWeights | None = None
    warnings: list[str] = Field(default_factory=list)
    auto_object_query: tuple[ObjectQueryTerm, ...] = ()
    results: tuple[SingleSearchResult, ...]


class TRAKESearchResponse(BaseModel):
    query_type: Literal["TRAKE"]
    original_query: str | None = None
    enhanced_query: str | None
    model_choices: list[str] = Field(default_factory=list)
    applied_weights: AppliedWeights | None = None
    warnings: list[str] = Field(default_factory=list)
    results: tuple[TRAKESearchResult, ...]


class TrafficSearchResponse(BaseModel):
    query_type: Literal["TRAFFIC"]
    original_query: str
    enhanced_query: str | None
    model_choices: list[str] = Field(default_factory=list)
    applied_weights: AppliedWeights | None = None
    warnings: list[str] = Field(default_factory=list)
    auto_object_query: tuple[ObjectQueryTerm, ...] = ()
    filtered_keyframes: int = 0
    results: tuple[SingleSearchResult, ...]


SearchResponse = Annotated[
    KISSearchResponse | VQASearchResponse | TRAKESearchResponse | TrafficSearchResponse,
    Field(discriminator="query_type"),
]


class ObjectLabelsResponse(BaseModel):
    available: bool
    labels: tuple[str, ...]


class TrafficCamera(BaseModel):
    model_config = ConfigDict(frozen=True)

    camera_id: str
    name: str
    streets: tuple[str, ...]
    video_ids: tuple[str, ...]


class TrafficOptionsResponse(BaseModel):
    available: bool
    cameras: tuple[TrafficCamera, ...]
    dates: tuple[str, ...]
    dayparts: tuple[Daypart, ...]
    weathers: tuple[Weather, ...]
