from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from aic_app.api.dependencies import SettingsDependency
from aic_app.constants import TOP_K_OPTIONS

router = APIRouter(tags=["system"])


class PublicConfigResponse(BaseModel):
    top_k_options: tuple[int, ...]
    default_top_k: int
    max_trake_events: int
    max_query_length: int
    max_answer_length: int
    retrieval_mode: Literal["mock"]
    gemini_mode: Literal["mock"]


@router.get("/config", response_model=PublicConfigResponse)
async def public_config(settings: SettingsDependency) -> PublicConfigResponse:
    return PublicConfigResponse(
        top_k_options=TOP_K_OPTIONS,
        default_top_k=settings.default_top_k,
        max_trake_events=settings.max_trake_events,
        max_query_length=settings.max_query_length,
        max_answer_length=settings.max_answer_length,
        retrieval_mode="mock",
        gemini_mode="mock",
    )
