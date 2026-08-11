import json
from pathlib import Path

import pytest

from repositories.manifest_repository import ManifestError, ManifestRepository


def manifest_json(*, image_path: str = "keyframes/frame.jpg") -> str:
    return json.dumps(
        {
            "version": 1,
            "keyframes": [
                {
                    "keyframe_id": "video/0000",
                    "video_id": "video",
                    "frame_id": 123,
                    "image_path": image_path,
                }
            ],
        }
    )


def test_manifest_is_read_and_parsed_only_once(tmp_path: Path) -> None:
    read_count = 0

    def read_text(_: Path) -> str:
        nonlocal read_count
        read_count += 1
        return manifest_json()

    repository = ManifestRepository(tmp_path, read_text=read_text)

    first = repository.load()
    second = repository.load()
    keyframe = repository.get_keyframe("video/0000")

    assert first is second
    assert keyframe.frame_id == 123
    assert read_count == 1


def test_manifest_rejects_duplicate_keyframe_ids(tmp_path: Path) -> None:
    payload = json.loads(manifest_json())
    payload["keyframes"].append(payload["keyframes"][0].copy())
    repository = ManifestRepository(
        tmp_path,
        read_text=lambda _: json.dumps(payload),
    )

    with pytest.raises(ManifestError, match="Duplicate keyframe_id"):
        repository.load()


@pytest.mark.parametrize(
    "image_path",
    ["../escape.jpg", "/absolute/frame.jpg", "C:/escape.jpg", "folder\\frame.jpg"],
)
def test_manifest_rejects_invalid_relative_paths(tmp_path: Path, image_path: str) -> None:
    repository = ManifestRepository(
        tmp_path,
        read_text=lambda _: manifest_json(image_path=image_path),
    )

    with pytest.raises(ManifestError):
        repository.load()
