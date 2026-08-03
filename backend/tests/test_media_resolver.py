from pathlib import Path

import pytest

from aic_app.services.media_resolver import MediaNotFound, SafeMediaResolver, UnsafeMediaPath


def test_media_resolver_returns_existing_file_inside_data_root(tmp_path: Path) -> None:
    media_directory = tmp_path / "keyframes"
    media_directory.mkdir()
    media_file = media_directory / "frame.jpg"
    media_file.write_bytes(b"fixture")
    resolver = SafeMediaResolver(tmp_path)

    assert resolver.resolve("keyframes/frame.jpg") == media_file.resolve()


@pytest.mark.parametrize(
    "path",
    ["../secret.txt", "/etc/passwd", "C:/Windows/win.ini", "folder\\escape.jpg"],
)
def test_media_resolver_blocks_path_traversal(tmp_path: Path, path: str) -> None:
    resolver = SafeMediaResolver(tmp_path)

    with pytest.raises(UnsafeMediaPath):
        resolver.resolve(path)


def test_media_resolver_reports_missing_safe_file(tmp_path: Path) -> None:
    resolver = SafeMediaResolver(tmp_path)

    with pytest.raises(MediaNotFound):
        resolver.resolve("keyframes/missing.jpg")
