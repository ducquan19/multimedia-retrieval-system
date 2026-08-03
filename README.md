# AIC 2026 Retrieval Inspector

A local web application for inspecting video-retrieval results, manually reranking candidates, and building submissions for the HCMC AI Challenge 2026.

> [!IMPORTANT]
> Retrieval and Gemini query enhancement currently run in **mock mode**. The application does not call Gemini, generate embeddings, query a vector database, or perform AI inference.

## Project status

The backend foundation is complete through Phase 3. The frontend currently provides an application shell and verifies connectivity to the API; the full search and result-inspection workspace will be implemented in the next phases.

| Capability | Status |
| --- | --- |
| FastAPI health and public configuration | Available |
| Validated KIS, VQA, and TRAKE search contracts | Available |
| Cached normalized manifest loader | Available |
| Deterministic fixture retrieval | Available |
| Safe media serving | Available |
| CSV submission preview and download | Available |
| React application shell and API health check | Available |
| Search forms and result inspector | Planned |
| Manual drag-and-drop reranking | Planned |
| Submission controls in the UI | Planned |
| Real AI retrieval and Gemini integration | Out of scope for the MVP |

## Supported query types

- **KIS — Textual Known Item Search:** submit `<video_id>,<frame_id>`.
- **VQA — Visual Question Answering:** submit `<video_id>,<frame_id>,<answer>`.
- **TRAKE — Temporal Retrieval and Alignment of Key Events:** submit `<video_id>,<frame_id_1>,...,<frame_id_n>`.

The order of submission rows is significant. The backend always preserves the order received from the client and never sorts rows using an old retrieval rank.

## Technology stack

### Backend

- Python 3.12+
- FastAPI and Uvicorn
- Pydantic v2 and pydantic-settings
- pytest and Ruff
- Stateless architecture with no database

### Frontend

- React and TypeScript strict mode
- Vite
- TanStack Query
- dnd-kit
- Vitest, React Testing Library, and Playwright

## Prerequisites

- Python 3.12 or later
- Node.js 22 or later
- npm 10 or later
- GNU Make is optional; every Make target has a direct command equivalent

## Quick start

### 1. Create a Python virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r .\backend\requirements.lock
python -m pip install --no-deps -e .\backend
npm --prefix frontend ci
```

The frontend is pinned by `frontend/package-lock.json`. Python dependencies are recorded in the PEP 751 `backend/pylock.toml`, with `backend/requirements.lock` provided for compatibility with commonly installed pip versions.

After activating the virtual environment, the equivalent Make command is:

```powershell
make install
```

### 3. Configure the environment

PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS or Linux:

```bash
cp .env.example .env
```

The defaults work for local development:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AIC_DATA_ROOT` | `./data` | Root directory for manifests, fixtures, and media |
| `AIC_FRONTEND_ORIGIN` | `http://localhost:5173` | Allowed frontend origin in development |
| `AIC_DEFAULT_TOP_K` | `20` | Default number of search candidates |
| `AIC_MAX_TRAKE_EVENTS` | `10` | Deployment-level TRAKE event limit |
| `VITE_API_BASE_URL` | Empty | Optional API base URL used by the built frontend |
| `VITE_DEV_API_TARGET` | `http://localhost:8000` | Vite development proxy target |
| `GEMINI_API_KEY` | Placeholder | Reserved for future work and not read by the MVP |

Do not commit `.env` or real credentials.

### 4. Run the application

Start the backend and frontend together:

```powershell
python scripts/dev.py
```

Or use:

```powershell
make dev
```

Local services:

- Frontend: <http://localhost:5173>
- Backend API: <http://localhost:8000>
- OpenAPI/Swagger UI: <http://localhost:8000/docs>
- Health endpoint: <http://localhost:8000/api/health>

The frontend should display `Backend connected: ok` when both services are available. Stop both processes with `Ctrl+C`.

To run each service in a separate terminal:

```powershell
python -m uvicorn aic_app.main:app --app-dir backend/src --reload --port 8000
```

```powershell
npm --prefix frontend run dev
```

During development, the frontend sends `/api` requests through the Vite proxy. Production API URLs are not hardcoded in the client.

## API overview

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Process health check |
| `GET` | `/api/config` | Public top-k, TRAKE, and mock-mode settings |
| `POST` | `/api/search` | Deterministic mock search for KIS, VQA, or TRAKE |
| `POST` | `/api/submissions/render` | Validate rows and return a CSV preview |
| `POST` | `/api/submissions/download` | Return the same CSV content as an attachment |
| `GET` | `/media/{relative_path}` | Safely serve a file below `AIC_DATA_ROOT` |

See [docs/API.md](docs/API.md) for the complete request and response contract.

### Example: mock KIS search

```powershell
$searchBody = @{
  query_type = "KIS"
  query = "a person opening a laptop"
  top_k = 5
  enhance_query = $true
  search_sources = @{
    image = $true
    asr = $false
    object = $false
    ocr = $false
  }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/search `
  -ContentType "application/json" `
  -Body $searchBody
```

### Example: render an ordered KIS submission

```powershell
$submissionBody = @{
  query_type = "KIS"
  filename = "kis-results.csv"
  rows = @(
    @{ video_id = "L02_V003"; frame_id = 910 },
    @{ video_id = "L01_V001"; frame_id = 505 }
  )
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/submissions/render `
  -ContentType "application/json" `
  -Body $submissionBody
```

Submission output is UTF-8 CSV without a header. VQA answers containing commas, quotes, newlines, or Unicode are escaped with Python's `csv.writer`. Download filenames are reduced to safe basenames and forced to use the `.csv` extension.

## Data layout

All runtime data lives below one data root, configured by `AIC_DATA_ROOT` and defaulting to `./data`.

```text
data/
├── manifest.json
├── fixtures/
│   └── search_results.json
├── keyframes/
├── videos/
├── metadata/
├── asr/
├── ocr/
└── objects/
```

The repository includes deterministic fixtures for all three query types and a valid mock keyframe image. A keyframe's actual `frame_id` comes from the manifest; it is never inferred from a filename such as `0000.jpg`.

See [docs/DATA_FORMAT.md](docs/DATA_FORMAT.md) for the normalized manifest contract.

## Quality checks

Run the complete current quality suite:

```powershell
python -m ruff check backend scripts
python -m ruff format --check backend scripts
python -m pytest backend
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

Equivalent grouped targets are available:

```powershell
make lint
make typecheck
make test
make build
```

Playwright is configured, but end-to-end flows will be added after the frontend search and submission workspaces are implemented.

## Project structure

```text
.
├── backend/              # FastAPI application, domain models, adapters, and tests
├── data/                 # Normalized manifest, fixtures, and local media
├── docs/                 # Product, architecture, API, data, and assumption documents
├── frontend/             # React/Vite application and frontend tests
├── scripts/dev.py        # Cross-platform local process runner
├── .env.example
├── Makefile
└── README.md
```

Important documentation:

- [Product specification](docs/PRODUCT_SPEC.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data format](docs/DATA_FORMAT.md)
- [API contract](docs/API.md)
- [Assumptions](docs/ASSUMPTIONS.md)

## Security boundaries

- Manifest and media paths must remain below `AIC_DATA_ROOT`.
- Absolute paths, traversal components, and unsafe media paths are rejected.
- Submission filenames are never used to write server-side files.
- Development CORS is limited to the configured local frontend origin.
- Secrets are not logged or returned to the client.
- The MVP has no authentication because it is intended as a local, single-team tool.

## Current limitations and roadmap

The backend search engine reads deterministic fixture data. Gemini enhancement adds a visible mock marker, and hybrid source flags are validated and passed through without performing vector search.

Remaining MVP phases:

1. Build typed frontend query forms and API integration.
2. Add KIS/VQA result inspection, answer editing, modal viewing, and reranking.
3. Add the TRAKE row workspace and row-level reranking.
4. Connect the frontend to submission preview/download and add end-to-end tests.
5. Complete the final security, performance, accessibility, and documentation audit.

Real Gemini calls, embedding generation, vector databases, OCR/ASR inference, automatic VQA answers, automatic TRAKE alignment, user accounts, and production cloud deployment remain outside the current MVP scope.
