from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from aic_app.api.dependencies import MediaResolverDependency
from aic_app.services.media_resolver import MediaNotFound, UnsafeMediaPath

router = APIRouter(tags=["media"])


@router.get("/media/{relative_path:path}", response_class=FileResponse)
async def media(relative_path: str, resolver: MediaResolverDependency) -> FileResponse:
    try:
        path = resolver.resolve(relative_path)
    except UnsafeMediaPath as exc:
        raise HTTPException(status_code=400, detail="Invalid media path") from exc
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail="Media not found") from exc
    return FileResponse(path)
