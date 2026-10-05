import json
from pathlib import Path

import pytest

from repositories.keyframe_metadata_repository import (
    KeyframeMetadataError,
    KeyframeMetadataRepository,
    keyframe_order_hash,
)


def manifest_bytes(*, image_path: str = "keyframes/frame.jpg", **extra: object) -> bytes:
    keyframe = {
        "keyframe_id": "video/0000",
        "video_id": "video",
        "frame_id": 123,
        "image_path": image_path,
        **extra,
    }
    return json.dumps({"version": 1, "keyframes": [keyframe]}).encode("utf-8")


def test_keyframes_are_read_and_parsed_only_once(tmp_path: Path) -> None:
    read_count = 0

    def read_bytes(_: Path) -> bytes:
        nonlocal read_count
        read_count += 1
        return manifest_bytes()

    repository = KeyframeMetadataRepository(tmp_path, read_bytes=read_bytes)

    first = repository.load()
    second = repository.load()
    keyframe = repository.get_keyframe("video/0000")

    assert first is second
    assert keyframe.frame_id == 123
    assert repository.index_of("video/0000") == 0
    assert repository.find_index("missing") is None
    assert read_count == 1


def test_duplicate_keyframe_ids_are_rejected(tmp_path: Path) -> None:
    payload = json.loads(manifest_bytes())
    payload["keyframes"].append(payload["keyframes"][0].copy())
    repository = KeyframeMetadataRepository(
        tmp_path, read_bytes=lambda _: json.dumps(payload).encode("utf-8")
    )

    with pytest.raises(KeyframeMetadataError, match="Duplicate keyframe_id"):
        repository.load()


@pytest.mark.parametrize(
    "image_path",
    ["../escape.jpg", "/absolute/frame.jpg", "C:/escape.jpg", "folder\\frame.jpg", "a//b.jpg", ""],
)
def test_invalid_relative_paths_are_rejected(tmp_path: Path, image_path: str) -> None:
    repository = KeyframeMetadataRepository(
        tmp_path, read_bytes=lambda _: manifest_bytes(image_path=image_path)
    )

    with pytest.raises(KeyframeMetadataError):
        repository.load()


@pytest.mark.parametrize(
    "extra",
    [{"frame_id": -1}, {"frame_id": True}, {"time_ms": -5}, {"unexpected": 1}, {"objects": {}}],
)
def test_invalid_fields_are_rejected(tmp_path: Path, extra: dict) -> None:
    repository = KeyframeMetadataRepository(tmp_path, read_bytes=lambda _: manifest_bytes(**extra))

    with pytest.raises(KeyframeMetadataError, match=r"keyframes\[0\]"):
        repository.load()


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(KeyframeMetadataError, match="Unable to load"):
        KeyframeMetadataRepository(tmp_path).load()


def test_order_hash_matches_the_builders_algorithm(tmp_path: Path) -> None:
    repository = KeyframeMetadataRepository(tmp_path, read_bytes=lambda _: manifest_bytes())

    # scripts/_common.py hashes "<keyframe_id>\n" for every keyframe in order.
    assert repository.order_hash() == keyframe_order_hash(["video/0000"])
    assert keyframe_order_hash(["a", "b"]) != keyframe_order_hash(["b", "a"])
