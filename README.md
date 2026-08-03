# AIC 2026 Retrieval Inspector

Local web app phục vụ kiểm tra kết quả truy xuất video, manual reranking và tạo submission cho KIS, VQA và TRAKE của HCMC AI Challenge 2026.

> **Trạng thái:** retrieval và Gemini enhancement đang ở chế độ mock. MVP không gọi Gemini, không tạo embedding và không dùng vector database.

## Yêu cầu hệ thống

- Python 3.12+
- Node.js 22+
- npm 10+
- GNU Make là tùy chọn; mọi lệnh đều có bản tương đương không cần Make.

## Cài đặt

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\backend\requirements.lock
python -m pip install --no-deps -e .\backend
npm --prefix frontend install
Copy-Item .env.example .env
```

Hoặc sau khi kích hoạt virtual environment:

```powershell
make install
```

Dependency frontend được pin trong `frontend/package-lock.json`. Dependency Python được khóa theo platform hiện tại trong PEP 751 `backend/pylock.toml`; `backend/requirements.lock` là danh sách exact pin tương thích với các bản pip phổ biến.

## Chạy local

Chạy cả hai service bằng một lệnh:

```powershell
python scripts/dev.py
```

Hoặc `make dev`. Frontend mở tại `http://localhost:5173`, backend tại `http://localhost:8000`, OpenAPI tại `http://localhost:8000/docs`.

Để chạy riêng từng service:

```powershell
python -m uvicorn aic_app.main:app --app-dir backend/src --reload --port 8000
npm --prefix frontend run dev
```

Frontend gọi đường dẫn `/api` qua Vite proxy trong development. Khi deploy SPA ở nơi khác, đặt `VITE_API_BASE_URL` lúc build; backend CORS lấy từ `AIC_FRONTEND_ORIGIN`. Không có production URL hardcode trong application client.

## Quality gates

```powershell
python -m ruff check backend scripts
python -m ruff format --check backend scripts
python -m pytest backend
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

Các target tương đương: `make lint`, `make typecheck`, `make test`, `make build`.

## Data

Tất cả runtime data nằm dưới `AIC_DATA_ROOT`, mặc định `./data`. Phase 2 cung cấp normalized `data/manifest.json`, deterministic fixture cho KIS/VQA/TRAKE và một mock keyframe SVG hợp lệ. Xem [định dạng dữ liệu](docs/DATA_FORMAT.md) và [API contract](docs/API.md).

Các endpoint hiện có:

- `GET /api/health`
- `GET /api/config`
- `POST /api/search`
- `POST /api/submissions/render`
- `POST /api/submissions/download`
- `GET /media/{relative_path}`

Ví dụ mock KIS search:

```powershell
$body = @{
  query_type = "KIS"
  query = "người đang mở laptop"
  top_k = 10
  enhance_query = $true
  search_sources = @{ image = $true; asr = $false; object = $false; ocr = $false }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/search `
  -ContentType "application/json" -Body $body
```

Ví dụ preview KIS submission theo đúng thứ tự `rows`:

```powershell
$submission = @{
  query_type = "KIS"
  filename = "kis-results.csv"
  rows = @(
    @{ video_id = "L02_V003"; frame_id = 910 },
    @{ video_id = "L01_V001"; frame_id = 505 }
  )
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/submissions/render `
  -ContentType "application/json" -Body $submission
```

## Cấu trúc

- `backend/`: FastAPI, Pydantic settings, pytest và Ruff.
- `frontend/`: React, TypeScript strict, Vite, TanStack Query, dnd-kit, Vitest/RTL và Playwright.
- `docs/`: product spec, architecture, data/API contract và assumptions.
- `scripts/dev.py`: process runner local cho backend và frontend.

## Giới hạn hiện tại

Backend search hiện chỉ đọc fixture deterministic; Gemini enhancement chỉ thêm marker `Mock` và hybrid flags chưa chạy vector search. Submission render/download đã hoạt động ở backend, nhưng frontend search forms, result inspector, drag/drop và submission UX sẽ được bổ sung trong Prompt 4-7. Không có database, authentication hoặc SDK AI.
