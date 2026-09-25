from fastapi import APIRouter, HTTPException

from core.dependencies import DresServiceDependency, SettingsDependency
from infrastructure.dres_client import DresError, DresNotConfigured
from schemas.dres import (
    DresEvaluation,
    DresStatusResponse,
    DresSubmitRequest,
    DresSubmitResponse,
)
from services.dres_service import DuplicateSubmission

router = APIRouter(prefix="/dres", tags=["dres"])


@router.get("/status", response_model=DresStatusResponse)
def dres_status(service: DresServiceDependency, settings: SettingsDependency) -> DresStatusResponse:
    return DresStatusResponse(
        configured=service.configured,
        username=settings.dres_username if service.configured else None,
    )


@router.get("/evaluations", response_model=list[DresEvaluation])
def list_evaluations(service: DresServiceDependency) -> list[DresEvaluation]:
    try:
        return service.list_evaluations()
    except DresNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DresError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/submit", response_model=DresSubmitResponse)
def submit(payload: DresSubmitRequest, service: DresServiceDependency) -> DresSubmitResponse:
    try:
        return service.submit(payload)
    except DuplicateSubmission as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DresNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DresError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
