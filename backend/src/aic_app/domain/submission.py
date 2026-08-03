from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

VideoId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
Filename = Annotated[str, StringConstraints(max_length=255)]
Answer = Annotated[str, StringConstraints(max_length=4_000)]
FrameId = Annotated[int, Field(ge=0)]


class KISSubmissionRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    video_id: VideoId
    frame_id: FrameId


class VQASubmissionRow(KISSubmissionRow):
    answer: Answer


class TRAKESubmissionRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    video_id: VideoId
    frame_ids: tuple[FrameId, ...] = Field(min_length=1, max_length=100)


class KISSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_type: Literal["KIS"]
    filename: Filename = "kis_submission.csv"
    rows: tuple[KISSubmissionRow, ...] = Field(min_length=1, max_length=100)


class VQASubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_type: Literal["VQA"]
    filename: Filename = "vqa_submission.csv"
    rows: tuple[VQASubmissionRow, ...] = Field(min_length=1, max_length=100)


class TRAKESubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_type: Literal["TRAKE"]
    filename: Filename = "trake_submission.csv"
    event_count: int = Field(ge=1, le=100)
    rows: tuple[TRAKESubmissionRow, ...] = Field(min_length=1, max_length=100)


SubmissionRequest = Annotated[
    KISSubmissionRequest | VQASubmissionRequest | TRAKESubmissionRequest,
    Field(discriminator="query_type"),
]


class SubmissionRenderResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    filename: str
    row_count: int = Field(ge=0, le=100)
    warnings: tuple[str, ...] = ()
