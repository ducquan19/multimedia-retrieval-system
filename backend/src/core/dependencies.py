from typing import Annotated

from fastapi import Depends, HTTPException, Request

from core.config import Settings
from infrastructure.hf_signed_url import HuggingFaceUrlSigner
from services.search_service import SearchService


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=503, detail="Settings not initialized.")
    return settings


def get_search_service(request: Request) -> SearchService:
    service = getattr(request.app.state, "search_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Search service is not ready yet.")
    return service


def get_private_url_signer(request: Request) -> HuggingFaceUrlSigner | None:
    """Shared signer (and its URL cache); None when AIC_HF_TOKEN is not configured."""
    return getattr(request.app.state, "private_url_signer", None)


SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
PrivateUrlSignerDependency = Annotated[
    HuggingFaceUrlSigner | None, Depends(get_private_url_signer)
]
SearchServiceDependency = Annotated[SearchService, Depends(get_search_service)]
