from dataclasses import dataclass
from typing import Any

# keyframes.json holds ~450k entries, so keyframes are slotted dataclasses validated with
# plain string checks instead of Pydantic models (several times less memory and load time).


def validate_data_relative_path(value: object) -> str:
    """Validate the portable, relative POSIX path syntax stored in the manifest."""

    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise ValueError("data path must be a non-empty POSIX-style relative path")
    if value.startswith("/") or (len(value) > 1 and value[1] == ":"):
        raise ValueError("absolute data paths are not allowed")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("data path cannot contain dot or traversal segments")
    return value


def _require_str(name: str, value: object, max_length: int) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= max_length:
        raise ValueError(f"{name} must be a string of 1..{max_length} characters")


def _require_non_negative_int(name: str, value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True, kw_only=True)
class Keyframe:
    keyframe_id: str
    video_id: str
    frame_id: int
    image_path: str
    # Original presentation time (ms) of frame_id; set for VFR videos where frame_id / fps is wrong.
    time_ms: int | None = None
    group_id: str | int | None = None
    video_path: str | None = None
    segment_id: str | None = None
    asr_text: str | None = None
    objects: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        _require_str("keyframe_id", self.keyframe_id, 256)
        _require_str("video_id", self.video_id, 128)
        _require_non_negative_int("frame_id", self.frame_id)
        _require_non_negative_int("time_ms", self.time_ms, optional=True)
        validate_data_relative_path(self.image_path)
        if self.video_path is not None:
            validate_data_relative_path(self.video_path)
        for name in ("segment_id", "asr_text"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
        if self.objects is not None and not isinstance(self.objects, list):
            raise ValueError("objects must be a list")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Keyframe":
        if not isinstance(data, dict):
            raise ValueError("keyframe entry must be an object")
        unknown = data.keys() - _KEYFRAME_FIELDS
        if unknown:
            raise ValueError(f"unknown keyframe fields: {sorted(unknown)}")
        return cls(**data)


_KEYFRAME_FIELDS = frozenset(Keyframe.__dataclass_fields__)


@dataclass(frozen=True, slots=True)
class KeyframeCollection:
    version: int
    keyframes: tuple[Keyframe, ...]

    @classmethod
    def from_dict(cls, data: Any) -> "KeyframeCollection":
        """Build from parsed keyframes.json. Consumes ``data``: converted entries are dropped
        from its list to keep the peak memory of loading ~450k keyframes low."""
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("keyframes.json must be an object with version 1")
        entries = data.get("keyframes")
        if not isinstance(entries, list):
            raise ValueError("keyframes.json must contain a keyframes list")
        keyframes = []
        # Every keyframe of a shot repeats the shot transcript: share one string per text.
        shared_texts: dict[str, str] = {}
        for position, entry in enumerate(entries):
            try:
                text = entry.get("asr_text") if isinstance(entry, dict) else None
                if isinstance(text, str):
                    entry["asr_text"] = shared_texts.setdefault(text, text)
                keyframes.append(Keyframe.from_dict(entry))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"keyframes[{position}]: {exc}") from exc
            entries[position] = None  # release the parsed dict as soon as it is converted
        return cls(version=1, keyframes=tuple(keyframes))
