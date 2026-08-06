from typing import Annotated

from fastapi import Depends, Request

from aic_app.config import Settings
from aic_app.services.media_resolver import SafeMediaResolver
from aic_app.services.search_service import SearchService
from aic_app.services.submission_service import SubmissionService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_search_service(request: Request) -> SearchService:
    return request.app.state.search_service


def get_media_resolver(request: Request) -> SafeMediaResolver:
    return request.app.state.media_resolver


def get_submission_service(request: Request) -> SubmissionService:
    return request.app.state.submission_service


SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
SearchServiceDependency = Annotated[SearchService, Depends(get_search_service)]
MediaResolverDependency = Annotated[SafeMediaResolver, Depends(get_media_resolver)]
SubmissionServiceDependency = Annotated[SubmissionService, Depends(get_submission_service)]
