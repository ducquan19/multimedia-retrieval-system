import json
from pathlib import Path

from repositories.keyframe_metadata_repository import KeyframeMetadataRepository


def repository_with(frame_ids: list[int], tmp_path: Path) -> KeyframeMetadataRepository:
    payload = {
        "version": 1,
        "keyframes": [
            {
                "keyframe_id": f"V1/{frame_id}",
                "video_id": "V1",
                "frame_id": frame_id,
                "image_path": f"keyframes/V1/{frame_id}.jpg",
            }
            # Shuffled on purpose: neighbors must follow frame order, not file order.
            for frame_id in reversed(frame_ids)
        ]
        + [
            {
                "keyframe_id": "V2/0",
                "video_id": "V2",
                "frame_id": 0,
                "image_path": "keyframes/V2/0.jpg",
            }
        ],
    }
    return KeyframeMetadataRepository(
        tmp_path, read_bytes=lambda _: json.dumps(payload).encode("utf-8")
    )


def test_neighbors_are_ordered_and_centered_on_the_requested_frame(tmp_path: Path) -> None:
    repository = repository_with([0, 100, 200, 300, 400, 500], tmp_path)

    window, center = repository.neighbors("V1", 300, radius=2)

    assert [item.frame_id for item in window] == [100, 200, 300, 400, 500]
    assert window[center].frame_id == 300


def test_neighbors_snap_to_the_closest_keyframe_and_clip_at_video_edges(
    tmp_path: Path,
) -> None:
    repository = repository_with([0, 100, 200], tmp_path)

    window, center = repository.neighbors("V1", 140, radius=5)
    assert [item.frame_id for item in window] == [0, 100, 200]
    assert window[center].frame_id == 100

    window, center = repository.neighbors("V1", 9999, radius=1)
    assert [item.frame_id for item in window] == [100, 200]
    assert window[center].frame_id == 200


def test_neighbors_of_an_unknown_video_are_empty(tmp_path: Path) -> None:
    repository = repository_with([0], tmp_path)

    assert repository.neighbors("missing", 0, radius=3) == ((), -1)
