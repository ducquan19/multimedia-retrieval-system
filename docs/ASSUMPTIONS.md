# Assumptions and open decisions

| ID | Assumption or decision | Change point |
| --- | --- | --- |
| A-001 | The application inspects and reranks results; users submit selections manually outside it. | Product scope and result UI |
| A-002 | Normalized keyframe metadata lives below `AIC_DATA_ROOT`. | Repositories and configuration |
| A-003 | `MAX_TRAKE_EVENTS` is configurable and defaults to 10. | Settings, config endpoint, and form |
| A-004 | Reranking and VQA edits exist only in the current frontend session. | Frontend result state |
| A-005 | `result_id` is the stable candidate identity used to retain edits while reranking. | Search response and frontend state |
| A-006 | Optional ASR, OCR, object, and media metadata may be absent without crashing the UI. | Schemas and UI fallbacks |
| A-007 | The application has no accounts, database, or persistence. | Deployment architecture |

## Explicitly out of scope

- Generating, parsing, previewing, downloading, or storing submission files.
- Sending a submission to the competition platform.
- Ground-truth scoring, authentication, and realtime collaboration.

## Open questions

1. Official limits for event/query and VQA-answer text.
2. Dataset updates and authoritative frame-index mapping.
3. Final production deployment and authentication requirements, if any.
