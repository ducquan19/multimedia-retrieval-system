import csv
from io import StringIO
from typing import Protocol

from schemas.submission import (
    KISSubmissionRequest,
    SubmissionRequest,
    TRAKESubmissionRequest,
    VQASubmissionRequest,
)


class SubmissionFormatter(Protocol):
    def format(self, request: SubmissionRequest) -> str: ...


class CsvSubmissionFormatter:
    """Canonical UTF-8 CSV formatter shared by preview and download."""

    def format(self, request: SubmissionRequest) -> str:
        output = StringIO(newline="")
        writer = csv.writer(output, dialect="excel", lineterminator="\r\n")

        if isinstance(request, KISSubmissionRequest):
            writer.writerows((row.video_id, row.frame_id) for row in request.rows)
        elif isinstance(request, VQASubmissionRequest):
            writer.writerows((row.video_id, row.frame_id, row.answer) for row in request.rows)
        elif isinstance(request, TRAKESubmissionRequest):
            writer.writerows((row.video_id, *row.frame_ids) for row in request.rows)
        else:  # pragma: no cover - guarded by the discriminated request union
            raise TypeError("Unsupported submission request")

        return output.getvalue()
