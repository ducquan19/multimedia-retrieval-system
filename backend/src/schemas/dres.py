from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

EvaluationId = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_-]{1,128}$")
]


class DresAnswer(BaseModel):
    """A KIS answer (mediaItemName + start/end in ms) or a text answer (QA / TRAKE)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    media_item_name: str | None = Field(
        default=None, alias="mediaItemName", min_length=1, max_length=128
    )
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    text: str | None = Field(default=None, min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def validate_shape(self) -> "DresAnswer":
        if self.text is not None:
            if any(v is not None for v in (self.media_item_name, self.start, self.end)):
                raise ValueError("a text answer cannot also carry mediaItemName/start/end")
            return self
        if self.media_item_name is None or self.start is None or self.end is None:
            raise ValueError("an answer needs either text or mediaItemName, start and end")
        if self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class DresAnswerSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    answers: tuple[DresAnswer, ...] = Field(min_length=1, max_length=50)


class DresSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    evaluation_id: EvaluationId
    answer_sets: tuple[DresAnswerSet, ...] = Field(alias="answerSets", min_length=1)
    allow_duplicate: bool = False

    def dres_body(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True, include={"answer_sets"})


class DresEvaluation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    type: str | None = None
    status: str | None = None


class DresStatusResponse(BaseModel):
    configured: bool
    username: str | None = None


class DresSubmitResponse(BaseModel):
    accepted: bool
    status_code: int
    submission: str | None = None
    description: str | None = None
    body: dict[str, Any]
