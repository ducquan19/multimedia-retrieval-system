from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

QueryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class SearchSources(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image: bool = True
    asr: bool = False
    object: bool = False
    ocr: bool = False

    @model_validator(mode="after")
    def require_one_source(self) -> "SearchSources":
        if not any((self.image, self.asr, self.object, self.ocr)):
            raise ValueError("at least one search source must be enabled")
        return self


class BaseSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    top_k: int = Field(default=20, ge=1, le=100)
    enhance_query: bool = False
    use_reranking: bool = False
    search_sources: SearchSources = Field(default_factory=SearchSources)
    model_choice: Literal["siglip", "beit3", "hybrid"] = "hybrid"


class KISSearchRequest(BaseSearchRequest):
    query_type: Literal["KIS"]
    query: QueryText


class VQASearchRequest(BaseSearchRequest):
    query_type: Literal["VQA"]
    query: QueryText


class TRAKEEventQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_index: int = Field(ge=1)
    query: QueryText


class TRAKESearchRequest(BaseSearchRequest):
    query_type: Literal["TRAKE"]
    main_query: QueryText
    events: tuple[TRAKEEventQuery, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_event_indices(self) -> "TRAKESearchRequest":
        expected = list(range(1, len(self.events) + 1))
        actual = [event.event_index for event in self.events]
        if actual != expected:
            raise ValueError("TRAKE event_index values must be continuous from 1")
        return self


SearchRequest = Annotated[
    KISSearchRequest | VQASearchRequest | TRAKESearchRequest,
    Field(discriminator="query_type"),
]


class SingleSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str
    rank: int = Field(ge=1)
    video_id: str
    frame_id: int = Field(ge=0)
    keyframe_url: str
    segment_id: str
    asr_text: str
    ocr_text: str
    objects: list[dict[str, Any]]
    similarity_score: float
    answer: str = ""


class TRAKEEventResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_index: int = Field(ge=1)
    frame_id: int = Field(ge=0)
    keyframe_url: str
    segment_id: str
    asr_text: str
    ocr_text: str
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
    retrieval_mode: Literal["hybrid", "siglip", "beit3"] = "hybrid"
    results: tuple[SingleSearchResult, ...]


class VQASearchResponse(BaseModel):
    query_type: Literal["VQA"]
    original_query: str
    enhanced_query: str | None
    retrieval_mode: Literal["hybrid", "siglip", "beit3"] = "hybrid"
    results: tuple[SingleSearchResult, ...]


class TRAKESearchResponse(BaseModel):
    query_type: Literal["TRAKE"]
    original_query: str
    enhanced_query: str | None
    retrieval_mode: Literal["hybrid", "siglip", "beit3"] = "hybrid"
    results: tuple[TRAKESearchResult, ...]


SearchResponse = Annotated[
    KISSearchResponse | VQASearchResponse | TRAKESearchResponse,
    Field(discriminator="query_type"),
]
