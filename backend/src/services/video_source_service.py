import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from infrastructure.hf_signed_url import SignedUrlError


class VideoSourceError(RuntimeError):
    """Raised when compact video metadata is missing or malformed."""


class VideoSourceNotFound(LookupError):
    """Raised when a video has neither a local file nor a remote source."""


class VideoSourceUnavailable(RuntimeError):
    """Raised when a private video cannot be signed (missing token or Hub failure)."""


class PrivateUrlSigner(Protocol):
    def sign(self, path_in_repo: str, *, refresh: bool = False) -> str: ...


@dataclass(frozen=True)
class ResolvedVideoSource:
    video_id: str
    url: str
    source: str
    fps: float
    time_offset_ms: int = 0


class VideoSourceService:
    _VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
    _PRIVATE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.mp4$")

    def __init__(
        self,
        data_root: Path,
        metadata_filename: str,
        private_signer: PrivateUrlSigner | None = None,
    ) -> None:
        self._data_root = data_root.resolve()
        self._metadata_path = self._data_root / metadata_filename
        self._private_signer = private_signer

    def resolve(self, video_id: str, *, refresh: bool = False) -> ResolvedVideoSource:
        if not self._VIDEO_ID_PATTERN.fullmatch(video_id):
            raise VideoSourceNotFound("Invalid video ID")

        entry = self._load_entry(video_id)
        fps = entry.get("fps")
        if not isinstance(fps, int | float) or isinstance(fps, bool) or fps <= 0:
            raise VideoSourceError(f"Invalid fps for video {video_id}")
        offset = entry.get("time_offset_ms", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise VideoSourceError(f"Invalid time_offset_ms for video {video_id}")

        local_path = self._data_root / "videos" / f"{video_id}.mp4"
        if local_path.is_file():
            return ResolvedVideoSource(
                video_id=video_id,
                url=f"/media/videos/{video_id}.mp4",
                source="local",
                fps=float(fps),
                time_offset_ms=offset,
            )
        # Organizers' original .mov files (N001-N010) keep their pts, so the browser's
        # currentTime is already the original time; time_offset_ms only applies to the
        # remuxed .mp4 copies that start at 0.
        if (self._data_root / "videos" / f"{video_id}.mov").is_file():
            return ResolvedVideoSource(
                video_id=video_id,
                url=f"/media/videos/{video_id}.mov",
                source="local",
                fps=float(fps),
                time_offset_ms=0,
            )

        remote_url = entry.get("remote_url")
        if isinstance(remote_url, str) and self._is_http_url(remote_url):
            return ResolvedVideoSource(
                video_id=video_id,
                url=remote_url,
                source="remote",
                fps=float(fps),
                time_offset_ms=offset,
            )

        private_path = entry.get("private_path")
        if isinstance(private_path, str):
            if not self._PRIVATE_PATH_PATTERN.fullmatch(private_path):
                raise VideoSourceError(f"Invalid private_path for video {video_id}")
            if self._private_signer is None:
                raise VideoSourceUnavailable(
                    f"{video_id} is stored in the private repository; set AIC_HF_TOKEN to play it"
                )
            try:
                url = self._private_signer.sign(private_path, refresh=refresh)
            except SignedUrlError as exc:
                raise VideoSourceUnavailable(str(exc)) from exc
            return ResolvedVideoSource(
                video_id=video_id,
                url=url,
                source="remote",
                fps=float(fps),
                time_offset_ms=offset,
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
