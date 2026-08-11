import json
from pathlib import Path

import pytest

from adapters.retrieval import FixtureRetrievalEngine, RetrievalDataError
from domain.search import SearchSources, TRAKEEventQuery, TRAKESearchRequest
from repositories.manifest_repository import ManifestRepository


def test_fixture_engine_rejects_trake_event_from_another_video(tmp_path: Path) -> None:
    manifest = {
        "version": 1,
        "keyframes": [
            {
                "keyframe_id": "video-a/0001",
                "video_id": "video-a",
                "frame_id": 10,
                "image_path": "keyframes/frame.svg",
            },
            {
                "keyframe_id": "video-b/0001",
                "video_id": "video-b",
                "frame_id": 20,
                "image_path": "keyframes/frame.svg",
            },
        ],
    }
    fixture = {
        "version": 1,
        "KIS": [],
        "VQA": [],
        "TRAKE": [
            {
                "result_id": "invalid-row",
                "video_id": "video-a",
                "similarity_score": 0.9,
                "events": [
                    {
                        "event_index": 1,
                        "keyframe_id": "video-a/0001",
                        "similarity_score": 0.9,
                    },
                    {
                        "event_index": 2,
                        "keyframe_id": "video-b/0001",
                        "similarity_score": 0.8,
                    },
                ],
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    engine = FixtureRetrievalEngine(ManifestRepository(tmp_path), fixture_path)
    request = TRAKESearchRequest(
        query_type="TRAKE",
        main_query="sequence",
        events=(
            TRAKEEventQuery(event_index=1, query="one"),
            TRAKEEventQuery(event_index=2, query="two"),
        ),
        top_k=5,
        search_sources=SearchSources(),
    )

    with pytest.raises(RetrievalDataError, match="row video_id"):
        engine.retrieve(request)
