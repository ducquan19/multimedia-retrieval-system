from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from core.config import Settings
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from repositories.object_repository import KeyframeObjectRepository
from repositories.traffic_repository import TrafficMetadataRepository
from services.dres_service import DresSubmissionService
from services.search_service import SearchService
from services.video_source_service import VideoSourceService


def _state(request: Request, name: str, not_ready: str) -> Any:
    value = getattr(request.app.state, name, None)
    if value is None:
        raise HTTPException(status_code=503, detail=not_ready)
    return value


def get_app_settings(request: Request) -> Settings:
    return _state(request, "settings", "Settings not initialized.")


def get_search_service(request: Request) -> SearchService:
    return _state(request, "search_service", "Search service is not ready yet.")


def get_video_sources(request: Request) -> VideoSourceService:
    return _state(request, "video_sources", "Video sources are not ready yet.")


def get_object_repository(request: Request) -> KeyframeObjectRepository:
    return _state(request, "object_repository", "Object index is not ready yet.")


def get_keyframe_repository(request: Request) -> KeyframeMetadataRepository:
    return _state(request, "keyframe_repository", "Keyframe metadata is not ready yet.")


def get_traffic_repository(request: Request) -> TrafficMetadataRepository:
    return _state(request, "traffic_repository", "Traffic metadata is not ready yet.")


def get_dres_service(request: Request) -> DresSubmissionService:
    return _state(request, "dres_service", "DRES service is not ready yet.")


SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
SearchServiceDependency = Annotated[SearchService, Depends(get_search_service)]
VideoSourcesDependency = Annotated[VideoSourceService, Depends(get_video_sources)]
DresServiceDependency = Annotated[DresSubmissionService, Depends(get_dres_service)]
ObjectRepositoryDependency = Annotated[KeyframeObjectRepository, Depends(get_object_repository)]
KeyframeRepositoryDependency = Annotated[
    KeyframeMetadataRepository, Depends(get_keyframe_repository)
]
TrafficRepositoryDependency = Annotated[TrafficMetadataRepository, Depends(get_traffic_repository)]
