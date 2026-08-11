from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from models.keyframe import KeyframeCollection, Keyframe


class KeyframeMetadataError(RuntimeError):
    """Raised when the normalized keyframes are missing or malformed."""


class KeyframeMetadataRepository:
    """Load and cache an immutable normalized keyframe collection once per process."""

    def __init__(
        self,
        data_root: Path,
        keyframes_filename: str = "keyframes.json",
        read_text: Callable[[Path], str] | None = None,
    ) -> None:
        self._keyframes_path = data_root / keyframes_filename
        self._read_text = read_text or (lambda path: path.read_text(encoding="utf-8"))
        self._collection: KeyframeCollection | None = None
        self._keyframes_by_id: dict[str, Keyframe] | None = None

    def load(self) -> KeyframeCollection:
        if self._collection is not None:
            return self._collection

        try:
            raw_data = self._read_text(self._keyframes_path)
            collection = KeyframeCollection.model_validate_json(raw_data)
        except (OSError, ValidationError) as exc:
            raise KeyframeMetadataError("Unable to load the normalized data keyframes") from exc

        keyframes_by_id: dict[str, Keyframe] = {}
        for keyframe in collection.keyframes:
            if keyframe.keyframe_id in keyframes_by_id:
                raise KeyframeMetadataError(f"Duplicate keyframe_id: {keyframe.keyframe_id}")
            keyframes_by_id[keyframe.keyframe_id] = keyframe

        self._collection = collection
        self._keyframes_by_id = keyframes_by_id
        return collection

    def get_keyframe(self, keyframe_id: str) -> Keyframe:
        self.load()
        assert self._keyframes_by_id is not None
        try:
            return self._keyframes_by_id[keyframe_id]
        except KeyError as exc:
            raise KeyframeMetadataError(f"Unknown keyframe_id: {keyframe_id}") from exc
