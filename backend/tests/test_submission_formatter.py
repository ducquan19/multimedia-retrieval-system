from adapters.submission_csv import CsvSubmissionFormatter
from domain.submission import (
    KISSubmissionRequest,
    KISSubmissionRow,
    TRAKESubmissionRequest,
    TRAKESubmissionRow,
    VQASubmissionRequest,
    VQASubmissionRow,
)


def test_kis_format_has_no_header_and_preserves_row_order() -> None:
    request = KISSubmissionRequest(
        query_type="KIS",
        rows=(
            KISSubmissionRow(video_id="L02_V003", frame_id=910),
            KISSubmissionRow(video_id="L01_V001", frame_id=505),
        ),
    )

    content = CsvSubmissionFormatter().format(request)

    assert content == "L02_V003,910\r\nL01_V001,505\r\n"


def test_vqa_format_escapes_unicode_comma_quote_and_newline() -> None:
    request = VQASubmissionRequest(
        query_type="VQA",
        rows=(
            VQASubmissionRow(video_id="L05_V005", frame_id=888, answer="màu xanh, đậm"),
            VQASubmissionRow(video_id="L06_V007", frame_id=111, answer='Cô ấy nói "đúng"'),
            VQASubmissionRow(video_id="L07_V001", frame_id=222, answer="dòng một\ndòng hai"),
        ),
    )

    content = CsvSubmissionFormatter().format(request)

    assert content == (
        'L05_V005,888,"màu xanh, đậm"\r\n'
        'L06_V007,111,"Cô ấy nói ""đúng"""\r\n'
        'L07_V001,222,"dòng một\ndòng hai"\r\n'
    )


def test_trake_format_uses_fixed_frame_order() -> None:
    request = TRAKESubmissionRequest(
        query_type="TRAKE",
        event_count=4,
        rows=(
            TRAKESubmissionRow(
                video_id="L10_V010",
                frame_ids=(101, 151, 203, 251),
            ),
        ),
    )

    content = CsvSubmissionFormatter().format(request)

    assert content == "L10_V010,101,151,203,251\r\n"
