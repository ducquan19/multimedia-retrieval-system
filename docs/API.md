# API contract

The backend exposes retrieval, public configuration, health, and media endpoints. It does not create, store, preview, download, or submit result files.

## `GET /api/health`

Returns the process health status.

## `GET /api/config`

Returns the UI limits:

```json
{
  "min_top_k": 1,
  "max_top_k": 100,
  "default_top_k": 50,
  "max_trake_events": 10,
  "max_query_length": 4000,
  "max_answer_length": 4000
}
```

`max_answer_length` limits VQA text edited in the current browser session. It is not a file-processing limit.

## `POST /api/search`

The request is a discriminated union selected by `query_type` (`KIS`, `VQA`, or `TRAKE`). Shared controls include `top_k`, query enhancement, reranking, selected search sources, and model choice.

KIS/VQA requests contain `query`. TRAKE requests contain `main_query` and an ordered `events` array. Responses contain candidate metadata used by the result inspectors, including video/frame identifiers, media URLs, scores, and available ASR/OCR/object context.

The current retrieval behavior and query enhancement depend on the configured runtime services. Result editing and reranking are kept only in frontend memory.

## `GET /media/{relative_path:path}`

Serves media below `AIC_DATA_ROOT`. Absolute paths, drive paths, traversal components, encoded traversal, and paths resolving outside the data root are rejected.

## Manual submission boundary

After reviewing or reranking candidates, the user copies the relevant identifiers and submits them through the external competition workflow. There is intentionally no submission API and no CSV handling in this application.
