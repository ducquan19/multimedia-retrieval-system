# AIC 2026 Retrieval Inspector — Product specification

## Purpose and scope

The application helps a team:

1. run KIS, VQA, or TRAKE retrieval queries;
2. inspect keyframes, scores, ASR, OCR, and object context;
3. edit VQA answers and rerank candidates locally;
4. identify the result values that will be submitted manually outside the application.

The product is a retrieval-result inspector, not a submission builder. It does not create, store, parse, preview, or download CSV files and does not communicate with a competition submission service.

## Common workflow

- Switch between KIS, VQA, and TRAKE query forms.
- Configure top-k, enhancement, reranking, search sources, and model choice.
- View loading, error, empty, and result states.
- Inspect candidate identifiers, scores, thumbnails, and available metadata.
- Open an accessible detail modal for a keyframe or TRAKE event.
- Rerank candidates with drag-and-drop or keyboard controls and restore the original order with `Reset order`.
- Manually copy the chosen identifiers into the external submission workflow.

## Query-specific behavior

### KIS

Results are sortable keyframe candidates containing the video ID, frame ID, score, media, and available context.

### VQA

Results use the KIS inspector and add an answer editor. Answers are keyed by `result_id`, stay attached to the correct candidate after reranking, and live only in the current browser session.

### TRAKE

Each candidate is a sortable video row with a fixed ordered event sequence. Event cells cannot be reordered independently. Malformed sequences are rejected by the result validator.

## Non-functional requirements

- React and strict TypeScript frontend; FastAPI and Pydantic backend.
- Media URLs are relative and constrained to the configured data root.
- Missing optional metadata and failed images have stable fallbacks.
- Dialogs support focus management and Escape/backdrop closing.
- The app has no user database or persistent editing state.

## Acceptance criteria

- KIS, VQA, and TRAKE searches render valid candidate inspectors.
- Candidate reranking works and can be reset without calling a submission endpoint.
- VQA edits stay attached to their candidate during reranking.
- TRAKE event count/order invariants are enforced.
- No UI control, client type, API route, service, formatter, test, or documentation promises CSV/submission-file handling.
