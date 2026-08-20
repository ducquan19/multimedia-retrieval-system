from fastapi import APIRouter, HTTPException

from core.dependencies import SearchServiceDependency, SettingsDependency
from repositories.keyframe_metadata_repository import KeyframeMetadataError
from schemas.search import SearchRequest, SearchResponse
from services.retrieval_service import RetrievalDataError
from services.search_service import SearchValidationError

router = APIRouter(tags=["search"])

@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Semantic Video Keyframe Search",
    description="""
    Perform a semantic search for keyframes using natural language.
    
    This endpoint supports multiple search strategies including SigLIP, BEiT3, or a Hybrid fusion of both.
    It returns a list of candidate keyframes along with their similarity scores.
    
    **Parameters:**
    - **query**: The search text query (e.g. "a person walking").
    - **model_choices**: List of retrieval models to use (e.g. ["siglip", "beit3"]). If multiple, RRF is used.
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

@router.post("/open-video/{video_id}")
def open_video(video_id: str, settings: SettingsDependency):
    import subprocess
    video_path = settings.data_root / "videos" / f"{video_id}.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    
    try:
        subprocess.Popen(['explorer', '/select,', str(video_path.resolve())])
        return {"status": "success", "message": f"Opened explorer at {video_path}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open video: {e}")
