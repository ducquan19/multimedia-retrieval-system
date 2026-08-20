from typing import Literal

from pydantic import BaseModel, Field


class VideoSourceResponse(BaseModel):
    video_id: str
    url: str
    source: Literal["local", "remote"]
    fps: float = Field(gt=0)
