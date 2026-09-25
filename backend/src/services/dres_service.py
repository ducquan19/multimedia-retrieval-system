import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

from infrastructure.dres_client import DresClient
from schemas.dres import DresEvaluation, DresSubmitRequest, DresSubmitResponse

logger = logging.getLogger(__name__)


class DuplicateSubmission(ValueError):
    """Raised when the exact same answer was already delivered to an evaluation."""


class DresSubmissionService:
    """Submits answers to DRES and refuses to resend an identical answer set.

    Every answer DRES received is appended to a JSONL log, which also restores the
    duplicate guard after a backend restart.
    """

    def __init__(self, client: DresClient, log_path: Path) -> None:
        self._client = client
        self._log_path = log_path
        self._lock = threading.Lock()
        self._submitted = self._load_submitted()

    @property
    def configured(self) -> bool:
        return self._client.configured

    def list_evaluations(self) -> list[DresEvaluation]:
        return [DresEvaluation.model_validate(item) for item in self._client.list_evaluations()]

    def submit(self, request: DresSubmitRequest) -> DresSubmitResponse:
        body = request.dres_body()
        key = self._key(request.evaluation_id, body)
        with self._lock:
            if key in self._submitted and not request.allow_duplicate:
                raise DuplicateSubmission(
                    "This exact answer was already submitted to this evaluation."
                )

        status_code, payload = self._client.submit(request.evaluation_id, body)
        payload_dict = payload if isinstance(payload, dict) else {}
        accepted = 200 <= status_code < 300 and payload_dict.get("status", True) is not False

        # A 4xx/5xx without a DRES verdict may not have been recorded by DRES, so only
        # answers DRES actually judged count as submitted.
        if 200 <= status_code < 300:
            with self._lock:
                self._submitted.add(key)
            self._append_log(request.evaluation_id, body, status_code, payload)

        return DresSubmitResponse(
            accepted=accepted,
            status_code=status_code,
            submission=_as_text(payload_dict.get("submission")),
            description=_as_text(payload_dict.get("description")),
            body=body,
        )

    @staticmethod
    def _key(evaluation_id: str, body: dict) -> str:
        return f"{evaluation_id}|{json.dumps(body, sort_keys=True, ensure_ascii=False)}"

    def _load_submitted(self) -> set[str]:
        submitted: set[str] = set()
        if not self._log_path.exists():
            return submitted
        with open(self._log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    submitted.add(self._key(entry["evaluation_id"], entry["body"]))
                except (ValueError, KeyError):
                    logger.warning("Skipping malformed line in %s", self._log_path)
        return submitted

    def _append_log(self, evaluation_id: str, body: dict, status_code: int, payload) -> None:
        entry = {
            "time": datetime.now(UTC).isoformat(),
            "evaluation_id": evaluation_id,
            "body": body,
            "status_code": status_code,
            "response": payload,
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.error("Could not write DRES submission log: %s", exc)


def _as_text(value) -> str | None:
    return None if value is None else str(value)
