from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from core.constants import DEFAULT_TOP_K, MAX_TOP_K, MIN_TOP_K

QueryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class KISQueryPlanEvent(BaseModel):
    """One observable or searchable event extracted from a raw KIS query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_index: int = Field(ge=1)
    source_span_vi: QueryText
    visual_query_en: str | None = None
    asr_query_vi: str | None = None
    importance: Literal["anchor", "supporting", "context"] = "supporting"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    inferred: bool = False

    @model_validator(mode="after")
    def require_searchable_content(self) -> "KISQueryPlanEvent":
        if not any(
            (
                self.visual_query_en and self.visual_query_en.strip(),
                self.asr_query_vi and self.asr_query_vi.strip(),
            )
        ):
            raise ValueError("a KIS plan event must contain a visual or ASR query")
        return self


class KISQueryPlan(BaseModel):
    """Editable search plan produced by Query Understanding & Planning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    search_mode: Literal["single_anchor", "multi_anchor", "temporal_sequence"]
    events: tuple[KISQueryPlanEvent, ...] = Field(min_length=1, max_length=10)
    warnings: tuple[str, ...] = ()
    planner_model: Literal["gemini-3.5-flash-lite"] = "gemini-3.5-flash-lite"

    @model_validator(mode="after")
    def validate_events(self) -> "KISQueryPlan":
        expected = list(range(1, len(self.events) + 1))
        actual = [event.event_index for event in self.events]
        if actual != expected:
            raise ValueError("KIS plan event_index values must be continuous from 1")
        if not any(event.importance == "anchor" for event in self.events):
            raise ValueError("a KIS query plan must contain at least one anchor event")
        return self


class KISQueryPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: QueryText


class ObjectQueryTerm(BaseModel):
    """One detected-object requirement, e.g. at least 2 "Person"."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    min_count: int = Field(default=1, ge=1, le=50)


class QueryVariants(BaseModel):
    variants: list[str] = Field(
        description="Exactly 1 highly descriptive English variation of the original query.",
        min_length=1,
        max_length=1,
    )
    w_vis: float = Field(
        default=1.0,
        description=(
            "Weight for visual search (e.g. objects, colors, actions). Value from 0.0 to 1.0."
        ),
    )
    w_asr: float = Field(
        default=0.0,
        description=(
            "Weight for ASR speech search (e.g. spoken dialog, conversations). "
            "Value from 0.0 to 1.0."
        ),
    )
    w_obj: float = Field(
        default=0.0,
        description="Weight for detected-object search. Value from 0.0 to 1.0.",
    )
    asr_query_vi: str | None = Field(
        default=None,
        description="Vietnamese keywords likely to be spoken, used for ASR BM25 search.",
    )
    objects: tuple[ObjectQueryTerm, ...] = Field(
        default=(),
        description="Detector classes that should be visible in the target frame.",
    )


class BatchVariantResult(BaseModel):
    event_index: int
    result: QueryVariants


class QueryVariantsBatch(BaseModel):
    results: list[BatchVariantResult] = Field(
        description="List of enhanced query variants for each event."
    )


class SearchSources(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image: bool = True
    asr: bool = False
    object: bool = False

    @model_validator(mode="after")
    def require_one_source(self) -> "SearchSources":
        if not any((self.image, self.asr, self.object)):
            raise ValueError("at least one search source must be enabled")
        return self


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


ClockText = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class TrafficFilters(BaseModel):
    """Metadata filters of the traffic videos; an empty list means no restriction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    camera_ids: tuple[str, ...] = Field(default=(), max_length=200)
    dates: tuple[str, ...] = Field(default=(), max_length=50)
    dayparts: tuple[Literal["morning", "midday", "night"], ...] = ()
    weathers: tuple[Literal["dry", "wet"], ...] = ()
    clock_from: ClockText | None = None
    clock_to: ClockText | None = None


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


class KISSearchResponse(BaseModel):
    query_type: Literal["KIS"]
    original_query: str
    enhanced_query: str | None
    model_choices: list[str] = Field(default_factory=list)
    applied_weights: dict[str, float] | None = None
    warnings: list[str] = Field(default_factory=list)
    query_plan: KISQueryPlan | None = None
    auto_object_query: tuple[ObjectQueryTerm, ...] = ()
    results: tuple[SingleSearchResult, ...]


class VQASearchResponse(BaseModel):
    query_type: Literal["VQA"]
    original_query: str
    enhanced_query: str | None
    model_choices: list[str] = Field(default_factory=list)
    applied_weights: dict[str, float] | None = None
    warnings: list[str] = Field(default_factory=list)
    auto_object_query: tuple[ObjectQueryTerm, ...] = ()
    results: tuple[SingleSearchResult, ...]


class TRAKESearchResponse(BaseModel):
    query_type: Literal["TRAKE"]
    original_query: str | None = None
    enhanced_query: str | None
    model_choices: list[str] = Field(default_factory=list)
    applied_weights: dict[str, float] | None = None
    warnings: list[str] = Field(default_factory=list)
    results: tuple[TRAKESearchResult, ...]


class TrafficSearchResponse(BaseModel):
    query_type: Literal["TRAFFIC"]
    original_query: str
    enhanced_query: str | None
    model_choices: list[str] = Field(default_factory=list)
    applied_weights: dict[str, float] | None = None
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
    dayparts: tuple[str, ...]
    weathers: tuple[str, ...]
