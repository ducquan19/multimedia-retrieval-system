import logging
import threading
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DresError(RuntimeError):
    """Raised when DRES cannot be reached or rejects the credentials."""


class DresNotConfigured(DresError):
    """Raised when the DRES credentials are missing from the environment."""


class DresClient:
    """Thin DRES v2 client that logs in lazily and re-logs in when the session expires."""

    def __init__(
        self,
        base_url: str,
        username: str | None,
        password: str | None,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )
        self._session_id: str | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._username and self._password)

    def list_evaluations(self) -> list[dict[str, Any]]:
        response = self._with_session(
            lambda session: self._http.get(
                "/api/v2/client/evaluation/list", params={"session": session}
            )
        )
        if response.status_code != 200:
            raise DresError(f"DRES evaluation list failed ({response.status_code})")
        return response.json()

    def submit(self, evaluation_id: str, body: dict[str, Any]) -> tuple[int, Any]:
        """Forward a submission and return DRES's status code and JSON body verbatim."""
        response = self._with_session(
            lambda session: self._http.post(
                f"/api/v2/submit/{evaluation_id}", params={"session": session}, json=body
            )
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"status": False, "description": response.text}
        logger.info("DRES submit to %s -> %s %s", evaluation_id, response.status_code, payload)
        return response.status_code, payload

    def _with_session(self, send) -> httpx.Response:
        try:
            response = send(self._session())
            if response.status_code == 401:
                # The DRES session expired or was revoked: log in again once and retry.
                response = send(self._session(refresh=True))
        except httpx.HTTPError as exc:
            raise DresError(f"Cannot reach DRES: {exc}") from exc
        return response

    def _session(self, refresh: bool = False) -> str:
        if not self.configured:
            raise DresNotConfigured(
                "DRES credentials are missing. Set AIC_DRES_USERNAME and AIC_DRES_PASSWORD."
            )
        with self._lock:
            if self._session_id is None or refresh:
                self._session_id = self._login()
            return self._session_id

    def _login(self) -> str:
        try:
            response = self._http.post(
                "/api/v2/login",
                json={"username": self._username, "password": self._password},
            )
        except httpx.HTTPError as exc:
            raise DresError(f"Cannot reach DRES: {exc}") from exc
        if response.status_code != 200:
            raise DresError(f"DRES login failed ({response.status_code})")
        session_id = response.json().get("sessionId")
        if not session_id:
            raise DresError("DRES login response has no sessionId")
        logger.info("Logged in to DRES as %s", self._username)
        return session_id
