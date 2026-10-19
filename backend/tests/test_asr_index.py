"""The ASR index is trusted only when it was built from the loaded keyframes.json."""

import json
from pathlib import Path

import pytest

from fakes import FakeElasticsearch
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from repositories.text_repository import (
    KeyframeTextRepository,
    TextIndexMismatch,
)


def keyframes_repository(tmp_path: Path, ids: list[str]) -> KeyframeMetadataRepository:
    entries = [
        {
            "keyframe_id": keyframe_id,
            "video_id": keyframe_id.split("/")[0],
            "frame_id": position,
            "image_path": f"keyframes/{keyframe_id}.jpg",
            "segment_id": f"{keyframe_id.split('/')[0]}_S{position:05d}",
        }
        for position, keyframe_id in enumerate(ids)
    ]
    (tmp_path / "keyframes.json").write_text(
        json.dumps({"version": 1, "keyframes": entries}), encoding="utf-8"
    )
    return KeyframeMetadataRepository(tmp_path)


def text_repository(
    keyframes: KeyframeMetadataRepository, meta: dict | None, clock=lambda: 0.0
) -> tuple[KeyframeTextRepository, FakeElasticsearch]:
    es = FakeElasticsearch(meta=meta)
    return KeyframeTextRepository("http://es.invalid", keyframes, es_client=es, clock=clock), es


IDS = ["L01_V001/0", "L01_V001/1", "M01_V001/0"]


def test_index_built_from_the_same_manifest_is_used(tmp_path: Path) -> None:
    keyframes = keyframes_repository(tmp_path, IDS)
    meta = {"keyframe_order": keyframes.order_hash(), "keyframe_count": 3}
    repository, _ = text_repository(keyframes, meta)

    assert repository.index_order_status() == ("ok", "ok")
    assert [c.faiss_id for c in repository.search_text("q", ["asr_text"], top_k=2)] == [0, 1]


def test_index_built_before_the_traffic_group_was_appended_stays_valid(tmp_path: Path) -> None:
    before = keyframes_repository(tmp_path, IDS).order_hash()
    # append_traffic_index.py adds group N after the keyframes the index was built from
    keyframes = keyframes_repository(tmp_path, [*IDS, "N001-V001/0"])
    repository, _ = text_repository(keyframes, {"keyframe_order": before, "keyframe_count": 3})

    assert repository.index_order_status()[0] == "ok"


def test_index_from_another_manifest_disables_asr(tmp_path: Path) -> None:
    other = keyframes_repository(tmp_path, ["M01_V001/0", *IDS[:2]]).order_hash()
    keyframes = keyframes_repository(tmp_path, IDS)
    repository, es = text_repository(keyframes, {"keyframe_order": other, "keyframe_count": 3})

    status, detail = repository.index_order_status()
    assert status == "mismatch"
    assert "build_es_index.py" in detail
    with pytest.raises(TextIndexMismatch):
        repository.search_text("q", ["asr_text"], top_k=2)
    assert es.queries == []


def test_index_longer_than_the_manifest_is_a_mismatch(tmp_path: Path) -> None:
    keyframes = keyframes_repository(tmp_path, IDS)
    meta = {"keyframe_order": keyframes.order_hash(), "keyframe_count": 4}
    repository, _ = text_repository(keyframes, meta)

    assert repository.index_order_status()[0] == "mismatch"


def test_index_without_recorded_order_is_searched_but_reported(tmp_path: Path) -> None:
    keyframes = keyframes_repository(tmp_path, IDS)
    repository, _ = text_repository(keyframes, None)

    status, detail = repository.index_order_status()
    assert status == "unverified"
    assert "build_es_index.py" in detail
    assert repository.search_text("q", ["asr_text"], top_k=1)


def test_rebuilt_index_is_picked_up_after_the_recheck_interval(tmp_path: Path) -> None:
    keyframes = keyframes_repository(tmp_path, IDS)
    now = [0.0]
    repository, es = text_repository(
        keyframes, {"keyframe_order": "stale", "keyframe_count": 3}, clock=lambda: now[0]
    )
    assert repository.index_order_status()[0] == "mismatch"

    es.indices.meta = {"keyframe_order": keyframes.order_hash(), "keyframe_count": 3}
    assert repository.index_order_status()[0] == "mismatch"  # cached
    now[0] += 61
    assert repository.index_order_status()[0] == "ok"


def test_transcripts_are_merged_from_asr_texts_json(tmp_path: Path) -> None:
    keyframes = keyframes_repository(tmp_path, IDS)
    (tmp_path / "asr_texts.json").write_text(
        json.dumps({"version": 1, "videos": {"L01_V001": {"L01_V001_S00001": "xin chào"}}}),
        encoding="utf-8",
    )

    loaded = keyframes.load().keyframes
    assert [keyframe.asr_text for keyframe in loaded] == [None, "xin chào", None]


def test_unreadable_asr_texts_json_does_not_block_startup(tmp_path: Path) -> None:
    keyframes = keyframes_repository(tmp_path, IDS)
    (tmp_path / "asr_texts.json").write_text("{not json", encoding="utf-8")

    assert len(keyframes.load().keyframes) == 3
