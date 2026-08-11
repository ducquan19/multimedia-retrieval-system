import pytest

from adapters.submission_csv import CsvSubmissionFormatter
from domain.submission import (
    KISSubmissionRequest,
    KISSubmissionRow,
    TRAKESubmissionRequest,
    TRAKESubmissionRow,
    VQASubmissionRequest,
    VQASubmissionRow,
)
from services.submission_service import (
    SubmissionService,
    SubmissionValidationError,
    sanitize_filename,
)


@pytest.mark.parametrize(
    ("raw_filename", "expected"),
    [
        ("../../evil.csv", "evil.csv"),
        ("..\\..\\evil.csv", "evil.csv"),
        ("results.txt", "results.csv"),
        ("kết quả.csv", "kết quả.csv"),
        ("NUL.csv", "_NUL.csv"),
        ("\0../../", "kis_submission.csv"),
    ],
)
def test_filename_is_sanitized(raw_filename: str, expected: str) -> None:
    assert sanitize_filename(raw_filename, "kis") == expected


def test_service_reports_empty_vqa_answers_without_rejecting_them() -> None:
    service = SubmissionService(CsvSubmissionFormatter(), max_answer_length=4_000)
    request = VQASubmissionRequest(
        query_type="VQA",
        filename="answers.csv",
        rows=(
            VQASubmissionRow(video_id="L01", frame_id=1, answer=""),
            VQASubmissionRow(video_id="L02", frame_id=2, answer="   "),
            VQASubmissionRow(video_id="L03", frame_id=3, answer="ba"),
        ),
    )

    rendered = service.render(request)

    assert rendered.row_count == 3
    assert rendered.warnings == ("2 VQA row(s) have an empty answer",)


def test_service_rejects_trake_rows_with_wrong_event_count() -> None:
    service = SubmissionService(CsvSubmissionFormatter(), max_answer_length=4_000)
    request = TRAKESubmissionRequest(
        query_type="TRAKE",
        event_count=3,
        rows=(TRAKESubmissionRow(video_id="L10", frame_ids=(1, 2)),),
    )

    with pytest.raises(SubmissionValidationError, match="invalid rows: 1"):
        service.render(request)


def test_service_uses_array_order_instead_of_any_external_rank() -> None:
    service = SubmissionService(CsvSubmissionFormatter(), max_answer_length=4_000)
    request = KISSubmissionRequest(
        query_type="KIS",
        rows=(
            KISSubmissionRow(video_id="second-promoted", frame_id=2),
            KISSubmissionRow(video_id="original-first", frame_id=1),
        ),
    )

    assert service.render(request).content.startswith("second-promoted,2\r\n")
