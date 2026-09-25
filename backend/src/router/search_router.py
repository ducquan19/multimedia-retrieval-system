from fastapi import APIRouter, HTTPException, Query

from core.dependencies import (
    KeyframeRepositoryDependency,
    ObjectRepositoryDependency,
    PrivateUrlSignerDependency,
    SearchServiceDependency,
    SettingsDependency,
    TrafficRepositoryDependency,
)
from repositories.keyframe_metadata_repository import KeyframeMetadataError
from schemas.search import (
    KISQueryPlan,
    KISQueryPlanRequest,
    ObjectLabelsResponse,
    SearchRequest,
    SearchResponse,
    TrafficOptionsResponse,
)
from schemas.video import VideoKeyframe, VideoKeyframesResponse, VideoSourceResponse
from services.retrieval_service import RetrievalDataError
from services.search_service import SearchValidationError
from services.video_source_service import (
    VideoSourceError,
    VideoSourceNotFound,
    VideoSourceService,
    VideoSourceUnavailable,
)

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


@router.get("/traffic/options", response_model=TrafficOptionsResponse)
def get_traffic_options(repository: TrafficRepositoryDependency) -> TrafficOptionsResponse:
    return repository.options()


@router.get("/videos/{video_id}/keyframes", response_model=VideoKeyframesResponse)
def get_video_keyframes(
    video_id: str,
    keyframes: KeyframeRepositoryDependency,
    objects: ObjectRepositoryDependency,
    frame_id: int = Query(ge=0),
    radius: int = Query(default=8, ge=1, le=60),
) -> VideoKeyframesResponse:
    """Keyframes around frame_id in the same video, for temporal context browsing."""
    try:
        window, center_index = keyframes.neighbors(video_id, frame_id, radius)
    except KeyframeMetadataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not window:
        raise HTTPException(status_code=404, detail=f"No keyframes for video {video_id}.")
    return VideoKeyframesResponse(
        video_id=video_id,
        center_index=center_index,
        keyframes=[
            VideoKeyframe(
                frame_id=item.frame_id,
                time_ms=item.time_ms,
                keyframe_url=f"/media/{item.image_path}",
                segment_id=item.segment_id or "",
                asr_text=item.asr_text or "",
                objects=item.objects or objects.objects_for(item.keyframe_id),
            )
            for item in window
        ],
    )


@router.get("/videos/{video_id}/source", response_model=VideoSourceResponse)
def get_video_source(
    video_id: str,
    settings: SettingsDependency,
    signer: PrivateUrlSignerDependency,
    refresh: bool = False,
) -> VideoSourceResponse:
    service = VideoSourceService(settings.data_root, settings.video_sources_filename, signer)
    try:
        source = service.resolve(video_id, refresh=refresh)
    except VideoSourceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VideoSourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VideoSourceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return VideoSourceResponse(
        video_id=source.video_id,
        url=source.url,
        source=source.source,
        fps=source.fps,
        time_offset_ms=source.time_offset_ms,
    )
