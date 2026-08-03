from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from aic_app.domain.manifest import Manifest, ManifestKeyframe


class ManifestError(RuntimeError):
    """Raised when the normalized manifest is missing or malformed."""


class ManifestRepository:
    """Load and cache an immutable normalized manifest once per process."""

    def __init__(
        self,
        data_root: Path,
        manifest_filename: str = "manifest.json",
        read_text: Callable[[Path], str] | None = None,
    ) -> None:
        self._manifest_path = data_root / manifest_filename
        self._read_text = read_text or (lambda path: path.read_text(encoding="utf-8"))
        self._manifest: Manifest | None = None
        self._keyframes_by_id: dict[str, ManifestKeyframe] | None = None

    def load(self) -> Manifest:
        if self._manifest is not None:
            return self._manifest

        try:
            raw_manifest = self._read_text(self._manifest_path)
            manifest = Manifest.model_validate_json(raw_manifest)
        except (OSError, ValidationError, ValueError) as exc:
            raise ManifestError("Unable to load the normalized data manifest") from exc

        keyframes_by_id: dict[str, ManifestKeyframe] = {}
        for keyframe in manifest.keyframes:
            if keyframe.keyframe_id in keyframes_by_id:
                raise ManifestError(f"Duplicate keyframe_id: {keyframe.keyframe_id}")
            keyframes_by_id[keyframe.keyframe_id] = keyframe

        self._manifest = manifest
        self._keyframes_by_id = keyframes_by_id
        return manifest

    def get_keyframe(self, keyframe_id: str) -> ManifestKeyframe:
        self.load()
        assert self._keyframes_by_id is not None
        try:
            return self._keyframes_by_id[keyframe_id]
        except KeyError as exc:
            raise ManifestError(f"Unknown keyframe_id: {keyframe_id}") from exc
