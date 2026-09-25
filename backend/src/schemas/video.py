from typing import Any, Literal

from pydantic import BaseModel, Field


class VideoSourceResponse(BaseModel):
    video_id: str
    url: str
    source: Literal["local", "remote"]
    fps: float = Field(gt=0)
    # Original pts of the first frame; the served file starts at 0, so
    # original time (ms) = currentTime * 1000 + time_offset_ms.
    time_offset_ms: int = Field(default=0, ge=0)


class VideoKeyframe(BaseModel):
    frame_id: int
    time_ms: int | None = None
    keyframe_url: str
    segment_id: str = ""
    asr_text: str = ""
    objects: list[dict[str, Any]] = Field(default_factory=list)


class VideoKeyframesResponse(BaseModel):
    video_id: str
    # Index in `keyframes` of the keyframe closest to the requested frame; -1 when empty.
    center_index: int
    keyframes: list[VideoKeyframe]
