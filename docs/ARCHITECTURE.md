# Architecture

## 1. Trạng thái repository tại Prompt 0

Repository là greenfield: chỉ có `README.md`, prompt pack và hai tài liệu nguồn. Không có source code, entrypoint, dependency manifest, lockfile, package manager đã chọn trong repo, test hoặc CI để tái sử dụng. Vì vậy các prompt sau sẽ scaffold mới thay vì rewrite code đang hoạt động.

## 2. Kiến trúc mục tiêu

```text
Browser / React SPA
  -> typed HTTP client + TanStack Query
  -> FastAPI routes
      -> SearchService
          -> RetrievalEngine protocol -> FixtureRetrievalEngine
          -> QueryEnhancer protocol   -> MockQueryEnhancer
          -> ManifestRepository       -> data/manifest.json (cached)
      -> SubmissionService -> CSV formatter
      -> SafeMediaResolver -> files below DATA_ROOT
```

Backend stateless. Frontend giữ query/session editing state, trong đó ordered result array và VQA answers theo `result_id` là nguồn sự thật cho submission.

## 3. Cấu trúc module dự kiến

```text
backend/
  pyproject.toml
  src/aic_app/
    main.py                     # app factory, middleware, router wiring
    config.py                   # pydantic-settings
    api/
      routes_health.py
      routes_config.py
      routes_search.py
      routes_submissions.py
      routes_media.py
    domain/
      search.py                 # discriminated request/response models
      submission.py
      manifest.py
    repositories/
      manifest_repository.py    # load, validate, cache
    services/
      search_service.py
      submission_service.py
      media_resolver.py
    adapters/
      retrieval.py              # protocol + fixture implementation
      query_enhancer.py         # protocol + mock implementation
      submission_csv.py         # canonical formatter
  tests/
frontend/
  package.json
  package-lock.json             # npm được chọn cho scaffold
  src/
    app/                        # providers, shell, tabs
    api/                        # typed client, errors, cancellation
    features/search/            # shared/KIS/VQA/TRAKE forms
    features/results/           # cards, TRAKE rows, reorder state
    features/submission/        # action bar, preview/download
    components/                 # modal, image fallback, controls
    styles/                     # tokens/global CSS
    test/
  e2e/
data/
  manifest.json
  fixtures/search_results.json
docs/
```

`npm` là package manager frontend mặc định vì Node cung cấp sẵn npm và prompt không yêu cầu pnpm/yarn; dependency versions sẽ được khóa trong `package-lock.json`. Python dùng `pyproject.toml`; môi trường cài đặt cụ thể sẽ được ghi trong README ở Prompt 1. Đây là **DECISION**, không phải quy định cuộc thi.

## 4. Luồng dữ liệu

### Search

1. Form tạo discriminated request theo query type và validate ít nhất một source.
2. TanStack Query hủy request trước khi gửi request mới.
3. FastAPI/Pydantic validate type, độ dài, top-k và TRAKE events.
4. SearchService gọi MockQueryEnhancer nếu bật, sau đó FixtureRetrievalEngine.
5. Engine lấy fixture, đối chiếu manifest, chuẩn hóa optional fields và cắt top-k.
6. UI lưu snapshot thứ tự ban đầu và ordered editing state riêng.

### Inspect/reorder

Thumbnail URL trỏ tới media endpoint an toàn. Modal dùng metadata đã có trong response; không preload video. Reorder cập nhật array và rank hiển thị. VQA answer map dùng `result_id`, không dùng array index.

### Submission

1. Frontend tạo payload từ ordered state hiện tại.
2. Render và download đi qua cùng SubmissionService/CSV formatter.
3. Backend validate row shape, sanitize filename và trả preview JSON hoặc attachment.

## 5. Ranh giới và khả năng thay thế

- `RetrievalEngine` che giấu fixture hôm nay và retrieval thật trong tương lai.
- `QueryEnhancer` là mock deterministic; provider Gemini sau này không đổi API/UI contract.
- `ManifestRepository` cô lập schema file nguồn không được BTC quy định đầy đủ.
- `SubmissionFormatter` cô lập giả định CSV để đổi delimiter/transport khi BTC công bố.
- Route layer chỉ chuyển đổi HTTP, không chứa formatting hoặc path resolution logic.

## 6. Security và reliability

- Mọi manifest path là relative; resolve/canonicalize và xác nhận descendant của `DATA_ROOT` trước khi đọc/trả file.
- Không đưa absolute server paths hoặc secret ra response/log client.
- Không thực thi metadata; Pydantic parse JSON có giới hạn.
- Filename chỉ là tên attachment, không dùng để ghi file server.
- CORS allowlist lấy từ settings và mặc định chỉ local dev.
- Manifest cache immutable sau khi load; lỗi fixture/data trả lỗi có cấu trúc.

## 7. Milestone implementation plan

### M1 - Scaffold và developer experience (Prompt 1)

Files/modules: `backend/pyproject.toml`, `backend/src/aic_app/{main,config}.py`, health route/test, `frontend/package.json`, Vite/TS configs, app shell/test, `.env.example`, `.gitignore`, `Makefile`, `README.md`.

Acceptance: backend health trả 200; frontend render và gọi health; lint/typecheck/unit tests/build pass; URL/CORS lấy từ env; lockfile tồn tại; không có DB/auth/AI dependency.

### M2 - Backend search/data (Prompt 2)

Files/modules: domain search/manifest models, `manifest_repository.py`, `media_resolver.py`, retrieval/query enhancer adapters, search/config routes, `data/manifest.json`, fixtures và backend tests.

Acceptance: request của cả ba loại validate; top-k truncation; enhance on/off; source flags đi qua service; TRAKE invariants; cache; missing optional data; traversal tests pass.

### M3 - Submission backend (Prompt 3)

Files/modules: domain submission models, `submission_csv.py`, submission service/routes/tests; cập nhật `docs/API.md` và assumptions.

Acceptance: đúng field/order cho ba loại; Unicode/comma/quote/newline; sanitize filename; render bằng download; TRAKE width mismatch trả 422.

### M4 - Frontend forms/integration (Prompt 4)

Files/modules: app providers/tabs, typed API client, shared controls, KIS/VQA/TRAKE forms và component tests.

Acceptance: payload typed đúng cho ba loại; dynamic events; source validation; cancellation; mock enhanced callout; loading/error/empty tests; lint/typecheck/build pass.

### M5 - KIS/VQA inspector (Prompt 5)

Files/modules: result store/reducer, sortable card/grid, detail modal, image fallback, VQA answer editor và tests.

Acceptance: metadata/score; accessible modal; pointer/keyboard/fallback reorder; reset; answer giữ đúng candidate; lazy/error images.

### M6 - TRAKE inspector (Prompt 6)

Files/modules: TRAKE response validator, sortable row/event cell, responsive table/container và tests.

Acceptance: đúng N cells, same-video/continuous-index validation, row-only reorder/reset, modal ASR và overflow behavior.

### M7 - Submission UX/E2E (Prompt 7)

Files/modules: submission payload builders, sticky action bar, preview modal, download client, Playwright specs.

Acceptance: edit/reorder luôn phản ánh preview/download; sanitize filename phản ánh UI; KIS/VQA/TRAKE E2E chạy với fixture server.

### M8 - Hardening/final audit (Prompt 8)

Files/modules: toàn repo, README/troubleshooting/docs và cấu hình quality gates.

Acceptance: correctness/performance/accessibility/security checklist được test; Ruff, pytest, ESLint, `tsc`, Vitest, production build và Playwright đều pass thật.
