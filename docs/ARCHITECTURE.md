# Architecture

## Overview

```text
Browser / React SPA
  -> typed HTTP client
  -> FastAPI routes
      -> SearchService
          -> RetrievalService
          -> QueryEnhancer
      -> repositories and model adapters
  -> media files below AIC_DATA_ROOT
```

The backend is stateless and has no submission or file-export service. The frontend keeps the current query, result order, and edited VQA answers in component state for the active session only.

## Main modules

```text
backend/src/
  factories/factory.py       # app creation, middleware, route wiring
  router/                    # health, config, and search routes
  schemas/                   # retrieval and search contracts
  services/                  # retrieval and search orchestration
  repositories/              # keyframe, text, and vector access
  infrastructure/            # embeddings, reranking, query enhancement

frontend/src/
  api/                       # typed search/config client
  features/search/           # KIS, VQA, and TRAKE forms
  features/results/          # inspectors, local reranking, detail modals
```

## Data flow

1. The search form builds a typed request and cancels any obsolete request.
2. FastAPI validates the request and delegates it to `SearchService`.
3. Retrieval services return candidate metadata and relative media URLs.
4. The frontend displays candidates and keeps reranking/VQA edits in memory.
5. The user reads the selected identifiers and submits them manually outside the app.

No step generates, stores, parses, previews, or downloads a CSV file.

## Security boundaries

- Media paths must resolve below `AIC_DATA_ROOT`.
- Server paths and secrets are not exposed to clients or logs.
- Request text and collection sizes are bounded by the API schemas/configuration.
- Development CORS is restricted to the configured frontend origin.
- The local single-team application has no authentication or persistent user state.
