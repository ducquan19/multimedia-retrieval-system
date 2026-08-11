from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from core.dependencies import SubmissionServiceDependency
from schemas.submission import SubmissionRenderResponse, SubmissionRequest
from services.submission_service import (
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


@router.post(
    "/render",
    response_model=SubmissionRenderResponse,
    summary="Render Submission Output",
    description="""
    Render a submission file without downloading it.
    
    Validates the submission payload and formats it according to the submission guidelines (e.g. KIS, VQA, TRAKE).
    This is useful for previewing the CSV content in the frontend before triggering a download.
    """,
    response_description="A response containing the rendered CSV string and the generated filename.",
)
async def render_submission(
    payload: SubmissionRequest, service: SubmissionServiceDependency
) -> SubmissionRenderResponse:
    return render_or_422(payload, service)


@router.post(
    "/download",
    summary="Download Submission CSV",
    description="""
    Generate and download the submission CSV file.
    
    This endpoint performs the same validation and rendering as `/render`, but returns a binary file stream 
    with the `Content-Disposition` header set appropriately so the browser downloads it as a CSV.
    """,
    response_description="A binary file response containing the CSV data.",
)
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
