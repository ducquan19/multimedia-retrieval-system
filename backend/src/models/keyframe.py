from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_data_relative_path(value: str) -> str:
    """Validate the portable, relative path syntax stored in the manifest."""

    if not value or "\0" in value or "\\" in value:
        raise ValueError("data path must be a non-empty POSIX-style relative path")

    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("absolute data paths are not allowed")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise ValueError("data path cannot contain dot or traversal segments")
    return value


class Keyframe(BaseModel):
    model_config = ConfigDict(frozen=True)

    keyframe_id: str = Field(min_length=1, max_length=256)
    video_id: str = Field(min_length=1, max_length=128)
    frame_id: int = Field(ge=0)
    # Original presentation time (ms) of frame_id; set for VFR videos where frame_id / fps is wrong.
    time_ms: int | None = Field(default=None, ge=0)
    group_id: str | int | None = None
    image_path: str
    video_path: str | None = None
    segment_id: str | None = None
    asr_text: str | None = None
    objects: list[dict[str, Any]] | None = None

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str) -> str:
        return validate_data_relative_path(value)

    @field_validator("video_path")
    @classmethod
    def validate_video_path(cls, value: str | None) -> str | None:
        return validate_data_relative_path(value) if value is not None else None


class KeyframeCollection(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: Literal[1]
    keyframes: tuple[Keyframe, ...]
