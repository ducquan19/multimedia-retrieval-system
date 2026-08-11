from fastapi import APIRouter, HTTPException

from core.dependencies import SearchServiceDependency
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
    - **model_choice**: The retrieval model to use ("siglip", "beit3", or "hybrid").
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
