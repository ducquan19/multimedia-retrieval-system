from typing import Annotated

from fastapi import Depends, Request, HTTPException
from functools import lru_cache
from pathlib import Path

from core.config import Settings
from services.search_service import SearchService
from services.submission_service import SubmissionService

from core.logger import SimpleLogger


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=503, detail="Settings not initialized.")
    return settings


def get_search_service(request: Request) -> SearchService:
    service = getattr(request.app.state, "search_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Search service is not ready yet.")
    return service


def get_submission_service(request: Request) -> SubmissionService:
    service = getattr(request.app.state, "submission_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Submission service is not ready yet.")
    return service


SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
SearchServiceDependency = Annotated[SearchService, Depends(get_search_service)]
SubmissionServiceDependency = Annotated[SubmissionService, Depends(get_submission_service)]
