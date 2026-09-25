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
- Google Gemini 3.5 Flash Lite (for Query Enhancement and KIS Query Understanding & Planning)
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
python -m pip install -r requirements.txt
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
| `AIC_GEMINI_API_KEY` | None | **Required** for AI Query Enhancement |
| `AIC_ENABLE_RERANKING` | `false` | Enable local re-ranking |

Search uses a code-managed default Top-K of `100` and allows values up to `500`.

### Advanced KIS query planning

The KIS search zone includes an opt-in **Query Understanding & Planning** workflow. When
enabled, **Understand query** sends the raw Vietnamese description to
`POST /api/search/kis/plan`. Gemini returns an editable structured plan containing visual
queries in English, Vietnamese ASR queries, event importance, and temporal strategy.
Review the plan and then run Search.

### Hybrid search and Enhance query

Search fuses three sources: **Image** (SigLIP / BEiT-3), **ASR** (BM25 over transcripts) and
**Object** (detected objects, see step 5 below). The checked sources are the modalities a
search may use. With **Enhance query**, Gemini rewrites the query into English, extracts
Vietnamese spoken keywords for ASR, picks detector classes (only from the labels in
`objects_index.json`) with minimum counts, and predicts a weight per modality. Objects typed
manually are always kept and Gemini's objects are added to them. Weights are renormalized over
the sources that actually returned candidates, and an ASR hit scores every keyframe of its shot.

### DRES submission

Set `AIC_DRES_USERNAME` and `AIC_DRES_PASSWORD` in `.env` (optionally `AIC_DRES_BASE_URL`,
default `https://eventretrieval.one`). The backend logs in, keeps the DRES session and renews it
when it expires; the browser never sees the credentials.

Open a result's detail and press **Submit DRES**. Pick the evaluation, review the editable
fields and the request body preview, then press **Xác nhận nộp**:

- **KIS**: `mediaItemName` + `start`/`end` in ms (default `frame_id / fps × 1000`).
- **VQA** (available on KIS results too): `QA-<ANSWER>-<VIDEO_ID>-<TIME(ms)>`.
- **TRAKE**: `TR-<VIDEO_ID>-<FRAME_ID1>,<FRAME_ID2>,...` from the whole candidate row.

When the video player is open, **Dùng frame đang xem** takes the time (or, for TRAKE, that
event's frame) from the frame being watched. Every answer DRES judged is appended to
`data/dres_submissions.jsonl`; resending an identical answer to the same evaluation is refused
unless you confirm **Vẫn nộp lại**.

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
   - [Keyframes Batch 1](https://kaggle.com/datasets/d7aa43eea17237235450ede4a409cb562ff02d218a1340f4d6bdcdfe19a9d50c)
   - [ASR Data](https://kaggle.com/datasets/e2642647173eb4867e6f7ca12b592843b60e5ddb16dc76f08288fd816c6d0fd5)
   - [BEiT-3 checkpoint](https://kaggle.com/datasets/d41406373d9f714c275a2fd01c5222f46437b426c357abf603195a41eafa3228)
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
5. **Build Object Index**: Required for the **Object** search source. Reads `objects/<video_id>/<n>.json`, `map-keyframes/<video_id>.csv` and `scenes/<video_id>.scenes.csv`, then writes `data/objects_index.json`. Keyframes of the M, N and S sets are matched to the provided keyframe with the same `frame_idx`; the self-extracted L keyframes receive the merged objects of every provided keyframe in the same shot. Restart the backend after rebuilding.
   ```powershell
   python scripts/build_object_index.py
   ```
   Detections below `--min-score` (default `0.3`) are dropped; `--shot-level-prefixes` (default `L`) selects the sets mapped by shot.
6. **Local Video Playback**: Place your raw `.mp4` video files into `data/videos/<video_id>.mp4`. The application allows you to seamlessly open these videos locally at exact keyframe timestamps directly from the UI using the "Open Local Video" feature!
7. **BEiT-3 Checkpoint**: Create a `checkpoint` folder in `data/checkpoint/` and place `beit3.spm` and `beit3_base_patch16_384_coco_retrieval.pth` inside it if using the BEiT-3 retriever.

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
