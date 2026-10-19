import numpy as np
import pytest
from fastapi.testclient import TestClient

from fakes import FRAME_STEP, FRAMES_PER_VIDEO, VIDEOS, keyframe_vectors


def _expected_order(faiss_id: int) -> list[int]:
    vectors = keyframe_vectors(len(VIDEOS) * FRAMES_PER_VIDEO)
    scores = vectors @ vectors[faiss_id]
    return [int(i) for i in np.argsort(-scores) if i != faiss_id]


def _faiss_id(result: dict) -> int:
    video, n = result["result_id"].split("/")
    return VIDEOS.index(video) * FRAMES_PER_VIDEO + int(n)


def test_similar_returns_the_nearest_keyframes_without_the_example(client: TestClient) -> None:
    response = client.post(
        "/api/search/similar",
        json={"video_id": "L01_V002", "frame_id": 10 * FRAME_STEP, "top_k": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query_type"] == "SIMILAR"
    assert (body["video_id"], body["frame_id"]) == ("L01_V002", 250)
    example = FRAMES_PER_VIDEO + 10
    assert [_faiss_id(r) for r in body["results"]] == _expected_order(example)[:5]
    assert [r["rank"] for r in body["results"]] == [1, 2, 3, 4, 5]
    vectors = keyframe_vectors(len(VIDEOS) * FRAMES_PER_VIDEO)
    best = body["results"][0]
    assert best["similarity_score"] == pytest.approx(
        float(vectors[_faiss_id(best)] @ vectors[example]), abs=1e-5
    )


def test_similar_fuses_several_models(client: TestClient) -> None:
    response = client.post(
        "/api/search/similar",
        json={
            "video_id": "L01_V001",
            "frame_id": 0,
            "top_k": 3,
            "model_choices": ["siglip", "beit3"],
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 3
    assert all(r["result_id"] != "L01_V001/000000" for r in results)
    assert results[0]["similarity_score"] >= results[-1]["similarity_score"]


def test_unknown_frame_is_404(client: TestClient) -> None:
    response = client.post("/api/search/similar", json={"video_id": "L01_V001", "frame_id": 13})

    assert response.status_code == 404
    assert "frame 13" in response.json()["detail"]


def test_similar_search_is_timed(client: TestClient) -> None:
    response = client.post("/api/search/similar", json={"video_id": "L01_V001", "frame_id": 0})

    assert "X-Request-ID" in response.headers
