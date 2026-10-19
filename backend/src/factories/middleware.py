"""HTTP middleware of the API: local-only access and per-search timing logs."""

import ipaddress
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.timing import format_stages, timed_request

logger = logging.getLogger(__name__)

_TIMED_PREFIX = "/api/search"


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def add_local_only_guard(app: FastAPI) -> None:
    """Refuse every request that does not come from this machine.

    The API has no authentication and submits to DRES with the team account, so it must not be
    reachable from the network by accident (e.g. ``uvicorn --host 0.0.0.0``). The Vite dev proxy
    connects from localhost and is unaffected.
    """

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.client.host if request.client else None
        if not _is_loopback(host):
            logger.warning("Refused %s %s from %s", request.method, request.url.path, host)
            return JSONResponse(
                {
                    "detail": "The API only accepts local requests "
                    "(set AIC_ALLOW_REMOTE_CLIENTS=true to share it on the network)."
                },
                status_code=403,
            )
        return await call_next(request)


def add_search_timing(app: FastAPI) -> None:
    """Log one line per search request with its duration per stage (see core.timing)."""

    @app.middleware("http")
    async def search_timing(request: Request, call_next):
        if not request.url.path.startswith(_TIMED_PREFIX):
            return await call_next(request)
        request_id = uuid.uuid4().hex[:8]
        started = time.perf_counter()
        with timed_request() as stages:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s %d in %.0fms [%s] id=%s",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
            format_stages(stages) or "no stages",
            request_id,
        )
        return response
