# ContextMesh v0.9 validation

## Automated regression

- `65 passed`
- Covers v0.1–v0.8 behavior plus v0.9 route-aware paging, cancellation/resume, scoped SSE, duplicate filenames, restart reconciliation and tolerant model JSON parsing.

## Real HTTP smoke

Run with a clean filesystem store and the bundled FastAPI server:

- `GET /health` → 200, version `0.9.0`
- Workspace `/` → 200
- Admin `/admin` → 200
- Uploaded two files with the same browser filename; stored independently as `same.txt` and `same-2.txt`
- Async ingest → `complete`, 2 required blocks
- One-submit background evaluation → `complete`, execution coverage `1.0`, 2/2 visited, final score emitted only after completion

## Correctness changes validated in v0.9

- Route max-context is an execution constraint, not display metadata.
- Oversized addressable blocks are exhaustively paged inside the same coverage unit.
- Cancellation leaves a resumable checkpoint and never fabricates a final score.
- Server-restart reconciliation marks orphaned in-process jobs `interrupted`.
- LLM JSON wrapped in Markdown fences or explanatory prose is parsed robustly; malformed final JSON fails loudly instead of becoming score 0.
- Duplicate upload names cannot overwrite one another.
