from fastapi import APIRouter
from pydantic import BaseModel

from core.constants import DEFAULT_TOP_K, MAX_TOP_K, MIN_TOP_K
from core.dependencies import SettingsDependency

router = APIRouter(tags=["system"])


class PublicConfigResponse(BaseModel):
    min_top_k: int
    max_top_k: int
    default_top_k: int
    max_trake_events: int
    max_query_length: int
    max_answer_length: int


@router.get("/config", response_model=PublicConfigResponse)
async def public_config(settings: SettingsDependency) -> PublicConfigResponse:
    return PublicConfigResponse(
        min_top_k=MIN_TOP_K,
        max_top_k=MAX_TOP_K,
        default_top_k=DEFAULT_TOP_K,
        max_trake_events=settings.max_trake_events,
        max_query_length=settings.max_query_length,
        max_answer_length=settings.max_answer_length,
    )
