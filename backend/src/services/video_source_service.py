import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class VideoSourceError(RuntimeError):
    """Raised when compact video metadata is missing or malformed."""


class VideoSourceNotFound(LookupError):
    """Raised when a video has neither a local file nor a remote source."""


@dataclass(frozen=True)
class ResolvedVideoSource:
    video_id: str
    url: str
    source: str
    fps: float


class VideoSourceService:
    _VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

    def __init__(self, data_root: Path, metadata_filename: str) -> None:
        self._data_root = data_root.resolve()
        self._metadata_path = self._data_root / metadata_filename

    def resolve(self, video_id: str) -> ResolvedVideoSource:
        if not self._VIDEO_ID_PATTERN.fullmatch(video_id):
            raise VideoSourceNotFound("Invalid video ID")

        entry = self._load_entry(video_id)
        fps = entry.get("fps")
        if not isinstance(fps, int | float) or isinstance(fps, bool) or fps <= 0:
            raise VideoSourceError(f"Invalid fps for video {video_id}")

        local_path = self._data_root / "videos" / f"{video_id}.mp4"
        if local_path.is_file():
            return ResolvedVideoSource(
                video_id=video_id,
                url=f"/media/videos/{video_id}.mp4",
                source="local",
                fps=float(fps),
            )

        remote_url = entry.get("remote_url")
        if isinstance(remote_url, str) and self._is_http_url(remote_url):
            return ResolvedVideoSource(
                video_id=video_id,
                url=remote_url,
                source="remote",
                fps=float(fps),
            )
        raise VideoSourceNotFound(f"Video source not found for {video_id}")

    def _load_entry(self, video_id: str) -> dict[str, Any]:
        try:
            payload = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VideoSourceError(
                f"Unable to load video metadata from {self._metadata_path.name}"
            ) from exc

        if payload.get("version") != 1 or not isinstance(payload.get("videos"), dict):
            raise VideoSourceError("Unsupported video metadata format")

        entry = payload["videos"].get(video_id)
        if not isinstance(entry, dict):
            raise VideoSourceNotFound(f"Video metadata not found for {video_id}")
        return entry

    @staticmethod
    def _is_http_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
