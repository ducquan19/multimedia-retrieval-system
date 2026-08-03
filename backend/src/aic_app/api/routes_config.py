from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from aic_app.config import Settings
from aic_app.constants import TOP_K_OPTIONS

router = APIRouter(tags=["system"])


class PublicConfigResponse(BaseModel):
    top_k_options: tuple[int, ...]
    default_top_k: int
    max_trake_events: int
    retrieval_mode: Literal["mock"]
    gemini_mode: Literal["mock"]


@router.get("/config", response_model=PublicConfigResponse)
async def public_config(request: Request) -> PublicConfigResponse:
    settings: Settings = request.app.state.settings
    return PublicConfigResponse(
        top_k_options=TOP_K_OPTIONS,
        default_top_k=settings.default_top_k,
        max_trake_events=settings.max_trake_events,
        retrieval_mode="mock",
        gemini_mode="mock",
    )
