import re
import unicodedata

from aic_app.adapters.submission_csv import SubmissionFormatter
from aic_app.domain.submission import (
    SubmissionRenderResponse,
    SubmissionRequest,
    TRAKESubmissionRequest,
    VQASubmissionRequest,
)

_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class SubmissionValidationError(ValueError):
    """Raised when rows conflict with request-level submission metadata."""


class SubmissionService:
    def __init__(self, formatter: SubmissionFormatter) -> None:
        self._formatter = formatter

    def render(self, request: SubmissionRequest) -> SubmissionRenderResponse:
        self._validate_request(request)
        filename = sanitize_filename(request.filename, request.query_type.lower())
        warnings = self._warnings(request)
        return SubmissionRenderResponse(
            content=self._formatter.format(request),
            filename=filename,
            row_count=len(request.rows),
            warnings=warnings,
        )

    @staticmethod
    def _validate_request(request: SubmissionRequest) -> None:
        if not isinstance(request, TRAKESubmissionRequest):
            return
        invalid_rows = [
            index
            for index, row in enumerate(request.rows, start=1)
            if len(row.frame_ids) != request.event_count
        ]
        if invalid_rows:
            row_list = ", ".join(str(index) for index in invalid_rows)
            raise SubmissionValidationError(
                f"TRAKE rows must each contain {request.event_count} frame IDs; "
                f"invalid rows: {row_list}"
            )

    @staticmethod
    def _warnings(request: SubmissionRequest) -> tuple[str, ...]:
        if not isinstance(request, VQASubmissionRequest):
            return ()
        empty_answer_count = sum(not row.answer.strip() for row in request.rows)
        if empty_answer_count == 0:
            return ()
        return (f"{empty_answer_count} VQA row(s) have an empty answer",)


def sanitize_filename(raw_filename: str, query_type: str) -> str:
    """Return a safe attachment basename with a CSV extension."""

    normalized_separators = raw_filename.replace("\\", "/")
    basename = normalized_separators.rsplit("/", maxsplit=1)[-1]
    basename = _INVALID_FILENAME_CHARACTERS.sub("_", basename).strip().strip(".")
    if not basename:
        basename = f"{query_type}_submission"

    stem = basename.rsplit(".", maxsplit=1)[0] if "." in basename else basename
    stem = stem.rstrip(" .") or f"{query_type}_submission"
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"

    max_stem_length = 255 - len(".csv")
    return f"{stem[:max_stem_length]}.csv"


def ascii_filename_fallback(filename: str) -> str:
    """Create a conservative ASCII fallback for Content-Disposition."""

    normalized = unicodedata.normalize("NFKD", filename)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_name or "submission.csv"
