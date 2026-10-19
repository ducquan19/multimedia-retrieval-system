"""Query value objects shared by the API, the services and the adapters.

They are Pydantic models because the API accepts them as they are and their validation rules
belong to the domain (e.g. a KIS plan needs an anchor event). They know nothing about HTTP;
schemas/search.py builds the request and response models on top of them.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    planner_model: str = Field(default="gemini-3.5-flash-lite", max_length=128)

    @model_validator(mode="after")
    def validate_events(self) -> "KISQueryPlan":
        expected = list(range(1, len(self.events) + 1))
        actual = [event.event_index for event in self.events]
        if actual != expected:
            raise ValueError("KIS plan event_index values must be continuous from 1")
        if not any(event.importance == "anchor" for event in self.events):
            raise ValueError("a KIS query plan must contain at least one anchor event")
        return self


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


ClockText = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Daypart = Literal["morning", "midday", "night"]
DAYPARTS: tuple[Daypart, ...] = ("morning", "midday", "night")
Weather = Literal["dry", "wet"]
WEATHERS: tuple[Weather, ...] = ("dry", "wet")


class TrafficFilters(BaseModel):
    """Metadata filters of the traffic videos; an empty list means no restriction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    camera_ids: tuple[str, ...] = Field(default=(), max_length=200)
    dates: tuple[str, ...] = Field(default=(), max_length=50)
    dayparts: tuple[Daypart, ...] = ()
    weathers: tuple[Weather, ...] = ()
    clock_from: ClockText | None = None
    clock_to: ClockText | None = None
