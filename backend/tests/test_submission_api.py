from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from main import create_app


def test_render_and_download_return_identical_utf8_content(client: TestClient) -> None:
    payload = {
        "query_type": "VQA",
        "filename": "câu trả lời.csv",
        "rows": [
            {"video_id": "L05_V005", "frame_id": 888, "answer": "màu xanh, đậm"},
            {"video_id": "L06_V007", "frame_id": 111, "answer": 'nói "đúng"'},
        ],
    }

    render_response = client.post("/api/submissions/render", json=payload)
    download_response = client.post("/api/submissions/download", json=payload)

    assert render_response.status_code == 200
    assert download_response.status_code == 200
    rendered = render_response.json()
    assert download_response.content.decode("utf-8") == rendered["content"]
    assert rendered["filename"] == "câu trả lời.csv"
    assert rendered["row_count"] == 2
    assert rendered["warnings"] == []
    assert download_response.headers["content-type"] == "text/csv; charset=utf-8"
    assert (
        "filename*=UTF-8''c%C3%A2u%20tr%E1%BA%A3%20l%E1%BB%9Di.csv"
        in (download_response.headers["content-disposition"])
    )


def test_render_preserves_client_row_order(client: TestClient) -> None:
    payload = {
        "query_type": "KIS",
        "filename": "kis.csv",
        "rows": [
            {"video_id": "L02_V003", "frame_id": 910},
            {"video_id": "L01_V001", "frame_id": 505},
        ],
    }

    response = client.post("/api/submissions/render", json=payload)

    assert response.status_code == 200
    assert response.json()["content"] == "L02_V003,910\r\nL01_V001,505\r\n"


def test_traversal_filename_is_sanitized_for_render_and_download(
    client: TestClient,
) -> None:
    payload = {
        "query_type": "KIS",
        "filename": "../../evil.csv",
        "rows": [{"video_id": "L01_V001", "frame_id": 505}],
    }

    rendered = client.post("/api/submissions/render", json=payload)
    downloaded = client.post("/api/submissions/download", json=payload)

    assert rendered.json()["filename"] == "evil.csv"
    assert 'filename="evil.csv"' in downloaded.headers["content-disposition"]
    assert ".." not in downloaded.headers["content-disposition"]


def test_empty_vqa_answer_returns_preview_warning(client: TestClient) -> None:
    response = client.post(
        "/api/submissions/render",
        json={
            "query_type": "VQA",
            "filename": "vqa.csv",
            "rows": [{"video_id": "L01", "frame_id": 1, "answer": ""}],
        },
    )

    assert response.status_code == 200
    assert response.json()["warnings"] == ["1 VQA row(s) have an empty answer"]


def test_trake_wrong_number_of_frames_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/submissions/render",
        json={
            "query_type": "TRAKE",
            "filename": "trake.csv",
            "event_count": 3,
            "rows": [{"video_id": "L10_V010", "frame_ids": [101, 151]}],
        },
    )

    assert response.status_code == 422
    assert "must each contain 3 frame IDs" in response.json()["detail"]


@pytest.mark.parametrize("endpoint", ["render", "download"])
def test_runtime_answer_length_is_enforced(app_settings: Settings, endpoint: str) -> None:
    settings = app_settings.model_copy(update={"max_answer_length": 3})

    with TestClient(create_app(settings)) as limited_client:
        response = limited_client.post(
            f"/api/submissions/{endpoint}",
            json={
                "query_type": "VQA",
                "filename": "vqa.csv",
                "rows": [{"video_id": "L01", "frame_id": 1, "answer": "four"}],
            },
        )

    assert response.status_code == 422
    assert "at most 3 characters" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "query_type": "KIS",
            "filename": "kis.csv",
            "rows": [{"video_id": "L01", "frame_id": -1}],
        },
        {
            "query_type": "VQA",
            "filename": "vqa.csv",
            "rows": [{"video_id": "L01", "frame_id": 1, "answer": 5}],
        },
        {
            "query_type": "TRAKE",
            "filename": "trake.csv",
            "event_count": 0,
            "rows": [{"video_id": "L10", "frame_ids": [1]}],
        },
    ],
)
def test_invalid_submission_rows_are_rejected(client: TestClient, payload: dict[str, Any]) -> None:
    assert client.post("/api/submissions/render", json=payload).status_code == 422
