from fastapi import APIRouter, HTTPException

from core.dependencies import (
    ObjectRepositoryDependency,
    SearchServiceDependency,
    SettingsDependency,
)
from repositories.keyframe_metadata_repository import KeyframeMetadataError
from schemas.search import (
    KISQueryPlan,
    KISQueryPlanRequest,
    ObjectLabelsResponse,
    SearchRequest,
    SearchResponse,
)
from schemas.video import VideoSourceResponse
from services.retrieval_service import RetrievalDataError
from services.search_service import SearchValidationError
from services.video_source_service import VideoSourceError, VideoSourceNotFound, VideoSourceService

router = APIRouter(tags=["search"])


@router.post(
    "/search/kis/plan",
    response_model=KISQueryPlan,
    summary="Understand and plan a KIS query",
)
async def plan_kis_query(
    payload: KISQueryPlanRequest, service: SearchServiceDependency
) -> KISQueryPlan:
    try:
        return service.plan_kis(payload.query)
    except SearchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Semantic Video Keyframe Search",
    description="""
    Perform a semantic search for keyframes using natural language.
    
    This endpoint supports multiple search strategies including SigLIP, BEiT3,
    or a Hybrid fusion of both.
    It returns a list of candidate keyframes along with their similarity scores.
    
    **Parameters:**
    - **query**: The search text query (e.g. "a person walking").
    - **model_choices**: List of retrieval models to use (e.g. ["siglip", "beit3"]).
      If multiple, RRF is used.
    - **top_k**: Maximum number of results to return.
    
    **Returns:**
    A list of top keyframes ordered by their fused similarity score.
    """,
    response_description="A response containing a list of top scored keyframes matching the query.",
)
async def search(payload: SearchRequest, service: SearchServiceDependency) -> SearchResponse:
    try:
        return service.search(payload)
    except SearchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (KeyframeMetadataError, RetrievalDataError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/objects/labels", response_model=ObjectLabelsResponse)
def get_object_labels(repository: ObjectRepositoryDependency) -> ObjectLabelsResponse:
    return ObjectLabelsResponse(available=repository.available, labels=repository.labels())


@router.get("/videos/{video_id}/source", response_model=VideoSourceResponse)
def get_video_source(video_id: str, settings: SettingsDependency) -> VideoSourceResponse:
    service = VideoSourceService(settings.data_root, settings.video_sources_filename)
    try:
        source = service.resolve(video_id)
    except VideoSourceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VideoSourceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return VideoSourceResponse(
        video_id=source.video_id,
        url=source.url,
        source=source.source,
        fps=source.fps,
    )
