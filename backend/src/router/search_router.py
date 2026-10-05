from fastapi import APIRouter, HTTPException, Query

from core.dependencies import (
    KeyframeRepositoryDependency,
    ObjectRepositoryDependency,
    SearchServiceDependency,
    TrafficRepositoryDependency,
    VideoSourcesDependency,
)
from infrastructure.retrieval import RetrievalDataError
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
from services.search_service import SearchValidationError
from services.video_source_service import (
    VideoSourceError,
    VideoSourceNotFound,
    VideoSourceUnavailable,
)

router = APIRouter(tags=["search"])

# Endpoints are plain `def`: they run torch, FAISS, Elasticsearch and Gemini synchronously,
# so FastAPI executes them in its threadpool instead of blocking the event loop (which would
# stall media, video and DRES requests while a search runs).


@router.post(
    "/search/kis/plan",
    response_model=KISQueryPlan,
    summary="Understand and plan a KIS query",
)
def plan_kis_query(payload: KISQueryPlanRequest, service: SearchServiceDependency) -> KISQueryPlan:
    try:
        return service.plan_kis(payload.query)
    except SearchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Hybrid video keyframe search",
    description=(
        "Search keyframes for a KIS, VQA, TRAKE or TRAFFIC query. Visual search uses SigLIP "
        "and/or BEiT-3 FAISS indexes, ASR uses Elasticsearch BM25 and the Object source uses "
        "the detector index; enabled sources are fused into one ranked list (TRAKE returns "
        "ranked event sequences of one video)."
    ),
    response_description="Ranked results with the query metadata and warnings.",
)
def search(payload: SearchRequest, service: SearchServiceDependency) -> SearchResponse:
    try:
        return service.search(payload)
    except SearchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (KeyframeMetadataError, RetrievalDataError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    video_sources: VideoSourcesDependency,
    refresh: bool = False,
) -> VideoSourceResponse:
    try:
        source = video_sources.resolve(video_id, refresh=refresh)
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
