from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from aic_app.domain.search import (
    SearchRequest,
    SingleSearchResult,
    TRAKEEventResult,
    TRAKESearchRequest,
    TRAKESearchResult,
)
from aic_app.repositories.manifest_repository import ManifestError, ManifestRepository


class RetrievalDataError(RuntimeError):
    """Raised when fixture retrieval data violates its contract."""


class RetrievalEngine(Protocol):
    def retrieve(
        self, request: SearchRequest
    ) -> tuple[SingleSearchResult | TRAKESearchResult, ...]: ...


class FixtureSingleCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result_id: str = Field(min_length=1)
    keyframe_id: str = Field(min_length=1)
    similarity_score: float = Field(ge=0, le=1)
    answer: str = ""


class FixtureTRAKEEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_index: int = Field(ge=1)
    keyframe_id: str = Field(min_length=1)
    similarity_score: float = Field(ge=0, le=1)


class FixtureTRAKECandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result_id: str = Field(min_length=1)
    video_id: str = Field(min_length=1)
    similarity_score: float = Field(ge=0, le=1)
    events: tuple[FixtureTRAKEEvent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_event_indices(self) -> "FixtureTRAKECandidate":
        expected = list(range(1, len(self.events) + 1))
        actual = [event.event_index for event in self.events]
        if actual != expected:
            raise ValueError("Fixture TRAKE event_index values must be continuous from 1")
        return self


class FixtureSearchData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    version: Literal[1]
    kis: tuple[FixtureSingleCandidate, ...] = Field(alias="KIS")
    vqa: tuple[FixtureSingleCandidate, ...] = Field(alias="VQA")
    trake: tuple[FixtureTRAKECandidate, ...] = Field(alias="TRAKE")

    @model_validator(mode="after")
    def validate_unique_result_ids(self) -> "FixtureSearchData":
        for candidates in (self.kis, self.vqa, self.trake):
            result_ids = [candidate.result_id for candidate in candidates]
            if len(result_ids) != len(set(result_ids)):
                raise ValueError("Fixture result_id values must be unique per query type")
        return self


class FixtureRetrievalEngine:
    def __init__(self, manifest_repository: ManifestRepository, fixture_path: Path) -> None:
        self._manifest_repository = manifest_repository
        self._fixture_path = fixture_path
        self._fixture_data: FixtureSearchData | None = None

    def retrieve(
        self, request: SearchRequest
    ) -> tuple[SingleSearchResult | TRAKESearchResult, ...]:
        fixture_data = self._load_fixture()
        if isinstance(request, TRAKESearchRequest):
            return self._retrieve_trake(request, fixture_data)

        candidates = fixture_data.kis if request.query_type == "KIS" else fixture_data.vqa
        results = tuple(
            self._hydrate_single(candidate, rank)
            for rank, candidate in enumerate(candidates[: request.top_k], start=1)
        )
        return results

    def _load_fixture(self) -> FixtureSearchData:
        if self._fixture_data is not None:
            return self._fixture_data
        try:
            raw_fixture = self._fixture_path.read_text(encoding="utf-8")
            fixture_data = FixtureSearchData.model_validate_json(raw_fixture)
        except (OSError, ValidationError, ValueError) as exc:
            raise RetrievalDataError("Unable to load fixture search results") from exc
        self._fixture_data = fixture_data
        return fixture_data

    def _hydrate_single(self, candidate: FixtureSingleCandidate, rank: int) -> SingleSearchResult:
        try:
            keyframe = self._manifest_repository.get_keyframe(candidate.keyframe_id)
        except ManifestError as exc:
            raise RetrievalDataError("Fixture references an unknown keyframe") from exc
        return SingleSearchResult(
            result_id=candidate.result_id,
            rank=rank,
            video_id=keyframe.video_id,
            frame_id=keyframe.frame_id,
            keyframe_url=self._media_url(keyframe.image_path),
            segment_id=keyframe.segment_id or "",
            asr_text=keyframe.asr_text or "",
            ocr_text=keyframe.ocr_text or "",
            objects=keyframe.objects or [],
            similarity_score=candidate.similarity_score,
            answer=candidate.answer,
        )

    def _retrieve_trake(
        self, request: TRAKESearchRequest, fixture_data: FixtureSearchData
    ) -> tuple[TRAKESearchResult, ...]:
        event_count = len(request.events)
        results: list[TRAKESearchResult] = []
        for candidate in fixture_data.trake:
            if len(candidate.events) < event_count:
                continue

            hydrated_events: list[TRAKEEventResult] = []
            for event in candidate.events[:event_count]:
                try:
                    keyframe = self._manifest_repository.get_keyframe(event.keyframe_id)
                except ManifestError as exc:
                    raise RetrievalDataError(
                        "TRAKE fixture references an unknown keyframe"
                    ) from exc
                if keyframe.video_id != candidate.video_id:
                    raise RetrievalDataError("Every TRAKE event must belong to the row video_id")
                hydrated_events.append(
                    TRAKEEventResult(
                        event_index=event.event_index,
                        frame_id=keyframe.frame_id,
                        keyframe_url=self._media_url(keyframe.image_path),
                        segment_id=keyframe.segment_id or "",
                        asr_text=keyframe.asr_text or "",
                        ocr_text=keyframe.ocr_text or "",
                        objects=keyframe.objects or [],
                        similarity_score=event.similarity_score,
                    )
                )

            expected_indices = list(range(1, event_count + 1))
            if [event.event_index for event in hydrated_events] != expected_indices:
                raise RetrievalDataError("TRAKE response event order is invalid")

            results.append(
                TRAKESearchResult(
                    result_id=candidate.result_id,
                    rank=len(results) + 1,
                    video_id=candidate.video_id,
                    similarity_score=candidate.similarity_score,
                    events=tuple(hydrated_events),
                )
            )
            if len(results) == request.top_k:
                break
        return tuple(results)

    @staticmethod
    def _media_url(image_path: str) -> str:
        return f"/media/{quote(image_path, safe='/')}"
