# Changelog

## v0.14.0

- Added durable upload sessions with persisted part state and resume after browser/server interruption.
- Added per-part SHA-256 validation and final SHA-256 computation for the local resumable backend.
- Added native S3/MinIO multipart transport with server-side upload IDs, presigned part URLs, remote part reconciliation, completion and abort.
- Added `/api/ingest-jobs/from-upload-sessions` so completed uploads hand off directly into the durable ingest queue.
- Workspace uploads now resume missing parts using browser-persisted session IDs rather than restarting whole-file multipart requests.
- Added optional `s3` dependency group for boto3 and S3/MinIO runtime configuration.
- Added resumable upload persistence/integrity/API regression tests.

## v0.13.0

- Replaced API-side `ThreadPoolExecutor` job submission with a durable SQLite WAL queue.
- Added atomic worker leases, lease expiry/recovery, persistent retry state, cancel requests and worker heartbeats.
- Added `contextmesh worker` for running ingest/evaluation workers independently from FastAPI.
- Kept an embedded development worker enabled by default; production can set `CONTEXTMESH_EMBEDDED_WORKER=0`.
- Added `GET /api/admin/queue` and Admin Queue & Workers observability.
- Docker Compose now runs the Web/API and worker as separate services against the same durable data volume.
- Corrected the Compose data environment variable to `CONTEXTMESH_DATA`.
- Added v0.13 queue persistence, lease-recovery, cancellation, retry and heartbeat regression tests.
- SQLite WAL is explicitly scoped to single-host deployments; the queue interface is designed for a later Redis/NATS/Postgres backend.

## v0.12.0

- Added a WAL-mode SQLite ContextBlock payload backend; new corpora no longer require one JSON file per block.
- Kept the legacy JSON-per-block backend selectable with `CONTEXTMESH_BLOCK_BACKEND=json`.
- Added lazy migration for v0.1-v0.11 JSON block corpora into the SQLite payload backend without changing manifest coverage IDs.
- Added batched `get_blocks()` reads for Explorer/API pagination.
- Added indexed page/slide/sheet/timeline co-location lookups and indexed explicit-reference resolution to avoid O(N²) corpus payload scans.
- Added `/api/corpora/{corpus_id}/storage` and surfaced payload backend/stored-block state in Workspace/Admin.
- Added `examples/storage_benchmark.py` and v0.12 storage regression tests.
- Local 100K smoke: ~1.50s payload write, ~0.63ms for five random reads. This is a smoke benchmark, not a million-block production SLA.

## v0.11.0

- Added a portable SQLite Context Catalog with FTS5 acceleration and automatic backfill for older corpora.
- Explorer/search now uses indexed ranking for navigation and scheduling while preserving the full manifest coverage set.
- Added `/api/corpora/{corpus_id}/catalog` with index backend, indexed block/asset counts, modality counts and readiness.
- Added typed evidence atoms for claims, numbers, dates, exceptions, contradictions and requirements, each linked to the raw source block.
- Final model judging now receives a bounded typed-evidence preservation channel in addition to hierarchical reduced notes.
- Evaluation/job APIs expose evidence-atom totals and per-kind counts.
- Workspace adds catalog health plus a Typed Evidence Inspector; Admin surfaces indexed-block scale.
- Added v0.11 regression tests covering catalog ranking without coverage filtering, typed evidence preservation and API exposure.

## v0.10.0 — Provider adapters and Context Studio

- Reworked Workspace into a three-pane Context Studio: Corpus / Context Explorer / Evaluation Inspector.
- Reworked Admin into a provider-aware operating console with route catalog, queue state, failures, cache telemetry and corpus inventory.
- Added provider catalog API and provider-specific adapters for Gemini generateContent, Anthropic Messages, OpenAI/Qwen/vLLM/OpenAI-compatible routes.
- Gemini adapter can carry native inline image/audio/video blocks when the route advertises those capabilities; unsupported modalities remain blocked rather than silently skipped.
- Added provider presets, endpoint/capability hints, local-vs-cloud route metadata and LMCache-friendly vLLM labeling.
- Preserved all v0.9 large-job reliability, route-aware paging, cancel/resume and full-coverage gates.
- Test suite: 68/68 passing.

## v0.9.0 — Large-job reliability and route-aware context

- Enforce route `max_context_tokens` with exhaustive in-block paging; an oversized ContextBlock is marked visited only after every route-sized slice has been inspected.
- Make reduction/finalization context-budget aware so reduced state cannot silently overflow smaller model routes.
- Add evaluation cancellation and checkpoint resume endpoints plus admin controls.
- Reconcile queued/running jobs after server restart into explicit `interrupted` state instead of leaving them stuck forever.
- Add ingest retry, duplicate-filename preservation, configurable per-file/batch upload limits, and browser upload-byte progress.
- Add job/corpus-scoped SSE filters.
- Add model-route health tests, per-route max parallel requests, configurable request timeout, and retry backoff.
- Harden real-model JSON parsing for fenced/wrapped JSON and segmented OpenAI-compatible content responses; malformed final scoring output now fails loudly instead of becoming a fake zero.
- Add v0.9 regression tests for context paging, cancel/resume, scoped events, duplicate names, restart recovery, and tolerant JSON parsing.

## 0.7.0

- added asynchronous file-level ingest jobs and durable queue state
- added SSE event stream for ingest/evaluation progress
- added one-submit background full-coverage evaluation jobs
- added persisted final score/rationale/status to evaluation checkpoints
- added atomic JSON writes for concurrent background jobs and UI readers
- added Context Explorer structure groups for page, slide, sheet, rows, section and timeline metadata
- added native PDF page fallback with pypdf
- added native PPTX slide fallback with python-pptx
- added native XLSX sheet/row-range fallback with openpyxl
- added previous/next boundary context for compatible model judges without changing coverage counting
- added model routing CRUD and Workspace route selection
- added provider usage accounting for prompt/completion/cached tokens, latency and estimated cost
- added LMCache/vLLM Prometheus telemetry parser and Admin dashboard
- added ingest queue, routing center and cache/token/latency/cost UI
- added full-coverage overflow design documentation
- expanded test suite to 30 tests

## 0.6.0

- runnable Workspace and Admin web console
- Context Explorer and `contextmesh serve`

## 0.5.0

- productized web control plane

## 0.4.0

- deterministic parallel full-coverage execution
- retry ledger and score-preservation benchmark

## 0.3.0

- bounded hierarchical reduction and multimodal payloads

## 0.2.0

- hierarchical ContextBlocks, ReaderSession and resume support

## 0.1.0

- first full-coverage runtime PoC

### v0.8 hardening follow-up
- Added `contextmesh audit` and `/api/corpora/{corpus_id}/audit` for corpus integrity validation.
- Audit detects missing/empty media payloads, empty text/table coverage blocks, missing parents/siblings, broken sibling backlinks and manifest count mismatches.
- Asset coverage reports now record SHA-256 of the exact uploaded source bytes.
- Added `fidelity-live` model-level needle recovery command; probes scan every block of the target asset and explicitly report unsupported modalities.
- Added `examples/generate_fidelity_corpus.py` producing real text, scan-PDF, PPTX, XLSX, DOCX, image, spoken-WAV and MP4 fixtures.
- Golden multi-format smoke currently ingests 8 real files into 13 required blocks with integrity audit passing.
