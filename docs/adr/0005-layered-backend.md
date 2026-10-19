# 0005. Backend chia tầng, luật phụ thuộc được test tự động

Trạng thái: Đang áp dụng (review kiến trúc 2026-10-19)

## Bối cảnh

Review kiến trúc (`docs/architecture/review/`) thấy schema của API (`schemas/search.py`) được dùng làm model nội bộ tới tận repository và adapter Gemini, interface của service nằm trong `infrastructure/`, và `RetrievalService` gánh mọi chế độ tìm cùng lúc.

## Quyết định

Các package và chiều phụ thuộc:

```text
router ──> services ──> repositories, infrastructure ──> models
   └──────> schemas ───────────────────────────────────────┘
```

- `models/`: domain (keyframe, ứng viên, value object của truy vấn, lỗi); không import tầng nào khác.
- `repositories/`, `infrastructure/`: adapter tới file, FAISS, ES, Gemini, model; chỉ dùng `models/` và các phần thuần của `core/` (`constants`, `intro_exclusion`, `timing`).
- `schemas/`: hợp đồng HTTP, dựng trên `models/query.py`.
- `services/`: điều phối; protocol nó cần nằm ở `services/ports.py`. Lõi tìm kiếm ở `services/retrieval/` (fusion, KIS theo plan, TRAKE, presenter dựng response).
- `core/container.py` và `factories/` là nơi duy nhất ghép mọi thứ lại.

`backend/tests/test_architecture.py` đọc import của mọi file và làm CI thất bại khi một luật bị vi phạm. Frontend lấy kiểu response từ `frontend/src/api/schema.gen.ts`, sinh từ OpenAPI bằng `scripts/generate_api_types.py`; CI báo lỗi khi file này cũ.

## Hệ quả

- Đổi một trường của API chỉ chạm `schemas/`, presenter và frontend; build frontend báo lỗi nếu quên.
- Thêm một tầng mới cần cập nhật luật trong `test_architecture.py`.

## Khi nào xem lại

Khi luật trong `test_architecture.py` phải nới ra nhiều lần cho cùng một nhu cầu: đó là dấu hiệu ranh giới đặt sai chỗ.
