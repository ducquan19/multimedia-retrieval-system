# Assumptions and Open Decisions

Tài liệu này chỉ ghi những điểm nguồn AIC 2026/CSV chưa quy định đầy đủ. Mỗi giả định phải được cô lập trong config hoặc adapter để sửa mà không rewrite toàn hệ thống.

| ID | Giả định/quyết định tạm thời | Lý do | Điểm thay đổi |
| --- | --- | --- | --- |
| A-001 | Submission là UTF-8 CSV, không header, một candidate mỗi dòng, extension `.csv` | PDF chỉ quy định field của một câu trả lời, chưa quy định file transport/delimiter/line ending | `SubmissionFormatter`, API docs/config |
| A-002 | VQA answer dùng CSV quoting chuẩn và cho phép rỗng kèm warning | Nguồn yêu cầu answer nhưng không nói hành vi khi chưa điền | submission schema/formatter/UI |
| A-003 | Dùng normalized `data/manifest.json` version 1 | BTC không cung cấp schema chung cho ASR/OCR/object/keyframe mapping | `ManifestRepository`/adapter |
| A-004 | `DATA_ROOT=./data` | CSV đề xuất lưu chung trong `data/`; prompt khóa default này | settings |
| A-005 | `MAX_TRAKE_EVENTS=10` mặc định và cấu hình được | Nguồn không nêu số event tối đa | settings/config endpoint/form |
| A-006 | Gemini enhance là mock deterministic/passthrough có nhãn Mock | CSV yêu cầu control, nhưng MVP cấm gọi Gemini thật | `QueryEnhancer` |
| A-007 | Bốn hybrid flags chỉ được validate/truyền qua adapter | MVP chưa có embedding/fusion thật | request schema/`RetrievalEngine` |
| A-008 | Search result là fixture/precomputed deterministic | Mục tiêu hiện tại là inspector, không phải retrieval engine | `FixtureRetrievalEngine` |
| A-009 | App local, single-team, không auth/database/persistence | Nguồn không yêu cầu account/collaboration | deployment/frontend state |
| A-010 | Reorder và VQA edits chỉ sống trong phiên frontend | Không có persistence requirement | frontend state |
| A-011 | Không tính R-Score/Final Score | Không có ground truth trong app | out of scope |
| A-012 | Manifest cache tồn tại suốt process; cập nhật data cần restart | MVP ưu tiên tốc độ và đơn giản | repository lifecycle |
| A-013 | Optional ASR/OCR/object/video path có thể thiếu và chuẩn hóa thành empty/null | PDF nói có video thiếu metadata; schema phụ không đầy đủ | manifest model/UI fallback |
| A-014 | `result_id` là stable unique identity của candidate | Cần giữ answer/reorder đúng candidate; nguồn không định nghĩa ID UI | fixture/response/frontend store |
| A-015 | `npm` + `package-lock.json` dùng cho frontend | Repo chưa có package manager; npm phù hợp Vite và có sẵn cùng Node | scaffold/README |
| A-016 | Preview/download không lưu file server-side | Chỉ cần render attachment, giảm rủi ro traversal | submission route |
| A-017 | CSV dùng line ending CRLF theo Python `excel` dialect và không có BOM | BTC chưa công bố line ending/BOM; CRLF tương thích phổ biến và render/download dùng cùng bytes | `CsvSubmissionFormatter` |
| A-018 | Filename input được rút về basename an toàn và luôn ép `.csv` | Filename chỉ là metadata attachment; không cho phép client chỉ định đường dẫn hoặc extension khác trong MVP | `SubmissionService` |

## Các điểm không phải giả định

- Tối đa 100 câu trả lời và các mốc R@1/5/20/50/100 là quy định PDF.
- KIS/VQA/TRAKE field order là quy định PDF.
- `frame_id` thật nằm trong metadata, không phải ordinal filename, là quy định PDF.
- Video là dữ liệu chính thức; keyframe/object/CLIP/metadata là dữ liệu hỗ trợ, theo PDF.
- Manual reorder, answer editing, ASR modal, image zoom, similarity score, top-k và controls Gemini/hybrid là nhu cầu CSV đã được chấp nhận cho MVP.

## Open questions cần xác nhận khi BTC cập nhật

1. Giao thức nộp chính thức, delimiter, extension, line ending và encoding/BOM.
2. Quy tắc canonicalization/semantic matching của VQA answer.
3. Schema chính thức cho metadata, ASR, OCR và objects ở batch AIC 2026.
4. Giới hạn số event/query và giới hạn độ dài text chính thức.
5. Dataset batch 2 và mapping frame index đi kèm.

Các câu hỏi này không chặn mock MVP; chúng được giữ sau adapter/config boundary nêu trong `ARCHITECTURE.md`.
