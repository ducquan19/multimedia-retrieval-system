from pathlib import Path, PurePosixPath

from aic_app.domain.manifest import validate_data_relative_path


class UnsafeMediaPath(ValueError):
    """Raised when a media path could escape DATA_ROOT."""


class MediaNotFound(FileNotFoundError):
    """Raised when a safe media path does not point to a file."""


class SafeMediaResolver:
    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root.resolve()

    def resolve(self, relative_path: str) -> Path:
        try:
            safe_path = validate_data_relative_path(relative_path)
        except ValueError as exc:
            raise UnsafeMediaPath("Unsafe media path") from exc

        candidate = self._data_root.joinpath(*PurePosixPath(safe_path).parts).resolve()
        if not candidate.is_relative_to(self._data_root):
            raise UnsafeMediaPath("Unsafe media path")
        if not candidate.is_file():
            raise MediaNotFound("Media file was not found")
        return candidate
