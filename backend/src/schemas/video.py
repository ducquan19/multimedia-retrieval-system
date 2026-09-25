from typing import Literal

from pydantic import BaseModel, Field


class VideoSourceResponse(BaseModel):
    video_id: str
    url: str
    source: Literal["local", "remote"]
    fps: float = Field(gt=0)
    # Original pts of the first frame; the served file starts at 0, so
    # original time (ms) = currentTime * 1000 + time_offset_ms.
    time_offset_ms: int = Field(default=0, ge=0)
