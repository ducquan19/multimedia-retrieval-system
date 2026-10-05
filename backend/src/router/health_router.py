from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ComponentStatus(BaseModel):
    ok: bool
    detail: str


class ReadinessResponse(BaseModel):
    ready: bool
    components: dict[str, ComponentStatus]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process answers HTTP."""
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def readiness(request: Request) -> JSONResponse:
    """Readiness: models, indexes and Elasticsearch, so a broken component is visible."""
    services = getattr(request.app.state, "services", None)
    if services is None:
        body = ReadinessResponse(
            ready=False, components={"startup": ComponentStatus(ok=False, detail="loading")}
        )
        return JSONResponse(body.model_dump(), status_code=503)

    components = {}
    for name, check in services.readiness_checks.items():
        try:
            ok, detail = check()
        except Exception as exc:  # noqa: BLE001 - a failing check is a not-ready component
            ok, detail = False, str(exc)
        components[name] = ComponentStatus(ok=ok, detail=detail)
    # SigLIP is the default visual model; the others degrade single features only.
    ready = components.get("siglip", ComponentStatus(ok=True, detail="")).ok
    body = ReadinessResponse(ready=ready, components=components)
    return JSONResponse(body.model_dump(), status_code=200 if ready else 503)
