import hashlib
import json
import threading
from bisect import bisect_left
from collections.abc import Callable
from pathlib import Path

from models.keyframe import Keyframe, KeyframeCollection


class KeyframeMetadataError(RuntimeError):
    """Raised when the normalized keyframes are missing or malformed."""


def keyframe_order_hash(keyframe_ids: list[str] | tuple[str, ...]) -> str:
    """SHA-1 of the keyframe_id order; the FAISS/ES builders store the same hash.

    Must stay identical to scripts/_common.py::keyframe_order_hash.
    """
    digest = hashlib.sha1()
    for keyframe_id in keyframe_ids:
        digest.update(keyframe_id.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


class KeyframeMetadataRepository:
    """Load and cache an immutable normalized keyframe collection once per process.

    The position of a keyframe in keyframes.json is its FAISS id in every vector index.
    """

    def __init__(
        self,
        data_root: Path,
        keyframes_filename: str = "keyframes.json",
        read_bytes: Callable[[Path], bytes] | None = None,
    ) -> None:
        self._keyframes_path = data_root / keyframes_filename
        self._read_bytes = read_bytes or (lambda path: path.read_bytes())
        self._lock = threading.Lock()
        self._collection: KeyframeCollection | None = None
        self._index_by_id: dict[str, int] = {}
        self._keyframes_by_video: dict[str, tuple[Keyframe, ...]] | None = None
        self._frame_ids_by_video: dict[str, list[int]] = {}
        self._order_hash: str | None = None

    def load(self) -> KeyframeCollection:
        collection = self._collection
        if collection is not None:
            return collection
        with self._lock:
            if self._collection is None:
                self._collection = self._read_collection()
            return self._collection

    def _read_collection(self) -> KeyframeCollection:
        try:
            raw_data = self._read_bytes(self._keyframes_path)
            # stdlib json: orjson needs ~4x more transient memory on this ~250 MB file.
            collection = KeyframeCollection.from_dict(json.loads(raw_data))
        except (OSError, ValueError) as exc:
            raise KeyframeMetadataError(
                f"Unable to load the normalized keyframes from {self._keyframes_path}: {exc}"
            ) from exc

        index_by_id: dict[str, int] = {}
        for position, keyframe in enumerate(collection.keyframes):
            if keyframe.keyframe_id in index_by_id:
                raise KeyframeMetadataError(f"Duplicate keyframe_id: {keyframe.keyframe_id}")
            index_by_id[keyframe.keyframe_id] = position
        self._index_by_id = index_by_id
        return collection

    def __len__(self) -> int:
        return len(self.load().keyframes)

    def get_keyframe(self, keyframe_id: str) -> Keyframe:
        return self.load().keyframes[self.index_of(keyframe_id)]

    def index_of(self, keyframe_id: str) -> int:
        """FAISS id (position in keyframes.json) of a keyframe."""
        self.load()
        try:
            return self._index_by_id[keyframe_id]
        except KeyError as exc:
            raise KeyframeMetadataError(f"Unknown keyframe_id: {keyframe_id}") from exc

    def find_index(self, keyframe_id: str) -> int | None:
        self.load()
        return self._index_by_id.get(keyframe_id)

    def order_hash(self) -> str:
        if self._order_hash is None:
            self._order_hash = keyframe_order_hash(
                [keyframe.keyframe_id for keyframe in self.load().keyframes]
            )
        return self._order_hash

    def video_keyframes(self, video_id: str) -> tuple[Keyframe, ...]:
        """All keyframes of one video, ordered by frame_id; empty for an unknown video."""
        if self._keyframes_by_video is None:
            keyframes = self.load().keyframes
            with self._lock:
                if self._keyframes_by_video is None:
                    grouped: dict[str, list[Keyframe]] = {}
                    for keyframe in keyframes:
                        grouped.setdefault(keyframe.video_id, []).append(keyframe)
                    by_video = {
                        key: tuple(sorted(frames, key=lambda item: item.frame_id))
                        for key, frames in grouped.items()
                    }
                    self._frame_ids_by_video = {
                        key: [item.frame_id for item in frames] for key, frames in by_video.items()
                    }
                    self._keyframes_by_video = by_video
        return self._keyframes_by_video.get(video_id, ())

    def neighbors(
        self, video_id: str, frame_id: int, radius: int
    ) -> tuple[tuple[Keyframe, ...], int]:
        """Up to `radius` keyframes on each side of the keyframe closest to frame_id.

        Returns the window and the index of that closest keyframe inside it.
        """
        frames = self.video_keyframes(video_id)
        if not frames:
            return (), -1
        frame_ids = self._frame_ids_by_video[video_id]
        center = bisect_left(frame_ids, frame_id)
        if center == len(frames) or (
            center > 0 and frame_id - frame_ids[center - 1] < frame_ids[center] - frame_id
        ):
            center -= 1
        start = max(0, center - radius)
        return frames[start : center + radius + 1], center - start
