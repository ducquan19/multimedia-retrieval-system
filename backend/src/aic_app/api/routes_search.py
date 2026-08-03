from fastapi import APIRouter, HTTPException

from aic_app.adapters.retrieval import RetrievalDataError
from aic_app.api.dependencies import SearchServiceDependency
from aic_app.domain.search import SearchRequest, SearchResponse
from aic_app.repositories.manifest_repository import ManifestError
from aic_app.services.search_service import SearchValidationError

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, service: SearchServiceDependency) -> SearchResponse:
    try:
        return service.search(payload)
    except SearchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ManifestError, RetrievalDataError) as exc:
        raise HTTPException(status_code=500, detail="Mock retrieval data is unavailable") from exc
