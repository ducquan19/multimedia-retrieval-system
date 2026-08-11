from fastapi import APIRouter
from pydantic import BaseModel

from core.dependencies import SettingsDependency
from core.constants import TOP_K_OPTIONS

router = APIRouter(tags=["system"])


class PublicConfigResponse(BaseModel):
    top_k_options: tuple[int, ...]
    default_top_k: int
    max_trake_events: int
    max_query_length: int
    max_answer_length: int
    retrieval_mode: str
    gemini_mode: str


@router.get("/config", response_model=PublicConfigResponse)
async def public_config(settings: SettingsDependency) -> PublicConfigResponse:
    return PublicConfigResponse(
        top_k_options=TOP_K_OPTIONS,
        default_top_k=settings.default_top_k,
        max_trake_events=settings.max_trake_events,
        max_query_length=settings.max_query_length,
        max_answer_length=settings.max_answer_length,
        retrieval_mode=settings.retrieval_mode,
        gemini_mode=settings.gemini_mode,
    )
