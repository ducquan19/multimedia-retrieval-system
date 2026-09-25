import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.config import Settings
from infrastructure.dres_client import DresClient
from router.dres_router import router as dres_router
from schemas.dres import DresSubmitRequest
from services.dres_service import DresSubmissionService


class FakeDres:
    """Minimal DRES v2 double that expires the first session after one use."""

    def __init__(self) -> None:
        self.logins = 0
        self.submissions: list[tuple[str, str, dict]] = []
        self.expire_next = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        session = request.url.params.get("session")
        if path == "/api/v2/login":
            assert json.loads(request.content) == {"username": "team", "password": "secret"}
            self.logins += 1
            return httpx.Response(
                200,
                json={
                    "id": "u1",
                    "username": "team",
                    "role": "PARTICIPANT",
                    "sessionId": f"s{self.logins}",
                },
            )
        if self.expire_next:
            self.expire_next = False
            return httpx.Response(401, json={"status": False, "description": "Unauthorized"})
        if path == "/api/v2/client/evaluation/list":
            return httpx.Response(
                200,
                json=[{"id": "ev1", "name": "Round 1", "type": "SYNCHRONOUS", "status": "ACTIVE"}],
            )
        if path.startswith("/api/v2/submit/"):
            body = json.loads(request.content)
            self.submissions.append((path.rsplit("/", 1)[1], session, body))
            return httpx.Response(
                200, json={"status": True, "submission": "CORRECT", "description": "ok"}
            )
        return httpx.Response(404)


def _service(tmp_path: Path, fake: FakeDres) -> DresSubmissionService:
    client = DresClient(
        "https://dres.test", "team", "secret", transport=httpx.MockTransport(fake.handler)
    )
    return DresSubmissionService(client, tmp_path / "dres_submissions.jsonl")


def _api(service: DresSubmissionService) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(dres_username="team", dres_password="secret")
    app.state.dres_service = service
    app.include_router(dres_router, prefix="/api")
    return TestClient(app)


KIS_BODY = {
    "evaluation_id": "ev1",
    "answerSets": [{"answers": [{"mediaItemName": "L21_V001", "start": 12000, "end": 12000}]}],
}


def test_submit_kis_logs_in_once_and_forwards_the_exact_body(tmp_path: Path) -> None:
    fake = FakeDres()
    api = _api(_service(tmp_path, fake))

    assert api.get("/api/dres/evaluations").json()[0]["id"] == "ev1"
    response = api.post("/api/dres/submit", json=KIS_BODY)

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["submission"] == "CORRECT"
    assert fake.logins == 1
    assert fake.submissions == [
        (
            "ev1",
            "s1",
            {
                "answerSets": [
                    {"answers": [{"mediaItemName": "L21_V001", "start": 12000, "end": 12000}]}
                ]
            },
        )
    ]


def test_expired_session_is_renewed_transparently(tmp_path: Path) -> None:
    fake = FakeDres()
    api = _api(_service(tmp_path, fake))
    api.get("/api/dres/evaluations")
    fake.expire_next = True

    response = api.post("/api/dres/submit", json=KIS_BODY)

    assert response.status_code == 200
    assert fake.logins == 2
    assert fake.submissions[0][1] == "s2"


def test_duplicate_answers_are_blocked_even_after_restart(tmp_path: Path) -> None:
    fake = FakeDres()
    api = _api(_service(tmp_path, fake))
    qa = {
        "evaluation_id": "ev1",
        "answerSets": [{"answers": [{"text": "QA-3-L21_V001-12000"}]}],
    }
    assert api.post("/api/dres/submit", json=qa).status_code == 200

    restarted = _api(_service(tmp_path, fake))
    assert restarted.post("/api/dres/submit", json=qa).status_code == 409
    assert (
        restarted.post("/api/dres/submit", json={**qa, "allow_duplicate": True}).status_code == 200
    )
    assert len(fake.submissions) == 2


def test_missing_credentials_return_503(tmp_path: Path) -> None:
    service = DresSubmissionService(
        DresClient("https://dres.test", None, None), tmp_path / "log.jsonl"
    )
    api = _api(service)

    assert api.post("/api/dres/submit", json=KIS_BODY).status_code == 503


@pytest.mark.parametrize(
    "answer",
    [
        {"mediaItemName": "L21_V001", "start": 5, "end": 1},
        {"mediaItemName": "L21_V001", "start": 5},
        {"text": "TR-L21_V001-1,2", "start": 5},
        {},
    ],
)
def test_malformed_answers_are_rejected(answer: dict) -> None:
    with pytest.raises(ValidationError):
        DresSubmitRequest.model_validate(
            {"evaluation_id": "ev1", "answerSets": [{"answers": [answer]}]}
        )
