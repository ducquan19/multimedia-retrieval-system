from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from aic_app.api.dependencies import SubmissionServiceDependency
from aic_app.domain.submission import SubmissionRenderResponse, SubmissionRequest
from aic_app.services.submission_service import (
    SubmissionService,
    SubmissionValidationError,
    ascii_filename_fallback,
)

router = APIRouter(prefix="/submissions", tags=["submissions"])


def render_or_422(
    payload: SubmissionRequest, service: SubmissionService
) -> SubmissionRenderResponse:
    try:
        return service.render(payload)
    except SubmissionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/render", response_model=SubmissionRenderResponse)
async def render_submission(
    payload: SubmissionRequest, service: SubmissionServiceDependency
) -> SubmissionRenderResponse:
    return render_or_422(payload, service)


@router.post("/download")
async def download_submission(
    payload: SubmissionRequest, service: SubmissionServiceDependency
) -> Response:
    rendered = render_or_422(payload, service)
    ascii_fallback = ascii_filename_fallback(rendered.filename).replace('"', "_")
    encoded_filename = quote(rendered.filename, safe="")
    content_disposition = (
        f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded_filename}"
    )
    return Response(
        content=rendered.content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disposition},
    )
