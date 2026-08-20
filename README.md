# AIC 2026 Retrieval Inspector

A local web application for inspecting video-retrieval results, manually reranking candidates, and building submissions for the HCMC AI Challenge 2026.

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
- FAISS (for SigLIP and BEiT-3 indexing)
- Elasticsearch (for ASR BM25 search)
- Google Gemini 2.5 Flash Lite (for Query Enhancement & TRAKE analysis)
- Stateless architecture with SQLite metadata DB

### Frontend

- React and TypeScript strict mode
- Vite
- TanStack Query
- dnd-kit (for manual result reranking)
- Vitest, React Testing Library, and Playwright

## Prerequisites

- Python 3.12 or later
- Node.js 22 or later
- npm 10 or later
- **Elasticsearch**: Required for ASR text search (can be run via Docker)
- **Google Gemini API Key**: Required for intelligent query enhancement (Developer API or Enterprise)

## Quick start

### 1. Create a Python virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r .\backend\requirements.lock
python -m pip install --no-deps -e .\backend
npm --prefix frontend ci
```

### 3. Configure the environment

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `AIC_DATA_ROOT` | `./data` | Root directory for manifests, FAISS indices, and media |
| `AIC_FRONTEND_ORIGIN` | `http://localhost:5173` | Allowed frontend origin in development |
| `AIC_DEFAULT_TOP_K` | `50` | Default number of search candidates |
| `AIC_GEMINI_API_KEY` | None | **Required** for AI Query Enhancement |
| `AIC_ENABLE_RERANKING` | `false` | Enable local re-ranking |

Do not commit `.env` or real credentials.

### 4. Run the application

Start the backend and frontend together (run Elasticsearch via Docker first if using ASR):

```powershell
docker compose up -d
python scripts/dev.py
```

Local services:
- Frontend: <http://localhost:5173>
- Backend API: <http://localhost:8000>
- OpenAPI/Swagger UI: <http://localhost:8000/docs>

## Data layout and Preparation

All runtime data lives below one data root, configured by `AIC_DATA_ROOT` and defaulting to `./data`.
Because datasets and models are large, they are excluded from Git.

### Recommended Setup Steps

1. **Download Kaggle Data**: Download the required datasets from Kaggle and extract them directly into `data/`:
   - [Embeddings](https://kaggle.com/datasets/c7b426cfb41d654ce995b9e35eb3a108167d65a6640caf0cd6af82e18d58b89a)
   - [Keyframes](https://kaggle.com/datasets/f6e43dae6bac933014eb004ae691fa652168994855a67a4e1f3850d9182478e3)
   - [ASR Data](https://kaggle.com/datasets/e2642647173eb4867e6f7ca12b592843b60e5ddb16dc76f08288fd816c6d0fd5)
2. **Build FAISS Index**: The Kaggle dataset only contains raw `.npy` embeddings. Run the indexing script to build `.index` files:
   ```powershell
   python scripts/build_faiss_index.py
   ```
3. **Generate Keyframes Manifest**: Required for the web application to serve images.
   ```powershell
   python scripts/generate_manifest.py
   ```
4. **Build Elasticsearch Index (BM25)**: For ASR search, ensure Elasticsearch is running, then build the index. *(Note: This script has been optimized with `ThreadPoolExecutor` and `orjson` for massive performance gains).*
   ```powershell
   python scripts/build_es_index.py
   ```
5. **Local Video Playback**: Place your raw `.mp4` video files into `data/videos/<video_id>.mp4`. The application allows you to seamlessly open these videos locally at exact keyframe timestamps directly from the UI using the "Open Local Video" feature!
6. **BEiT-3 Checkpoint**: Create a `checkpoint` folder in `data/checkpoint/` and place `beit3.spm` and `beit3_base_patch16_384_coco_retrieval.pth` inside it if using the BEiT-3 retriever.

### Expected Layout

```text
data/
├── keyframes.json
├── keyframes/
│   ├── L01_V001/
│   │   ├── S00001/
│   │   │   ├── F00001.jpg
│   │   │   └── ...
│   │   └── ...
│   └── ...
├── videos/
├── embeddings/
│   ├── siglip/
│   │   ├── L01_V001.npy
│   │   └── ...
│   └── beit3/
│       ├── L01_V001.npy
│       └── ...
├── indexing/
│   ├── siglip.index
│   └── beit3.index
├── checkpoint/             # BEiT-3 weights and tokenizer
├── asr/
├── ocr/
└── objects/
```

## Quality checks

Run the complete current quality suite:

```powershell
make lint
make typecheck
make test
make build
```

## Project structure

```text
.
├── backend/              # FastAPI application, domain models, adapters, and tests
├── data/                 # Normalized manifest, indices, and local media
├── docs/                 # Product, architecture, API, data, and assumption documents
├── frontend/             # React/Vite application and frontend tests
├── scripts/              # Data extraction (Kaggle), indexing, and dev runners
├── .env.example
├── Makefile
└── README.md
```
