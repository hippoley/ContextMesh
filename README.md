# ContextMesh

> v0.15: Full-Coverage Context Runtime with a reality-probe harness for testing retrieval-induced evidence blind spots.

**Full-coverage external context runtime for evaluating AI answers against corpora larger than a model context window.**

ContextMesh is not a RAG framework. Retrieval can decide **what is read first**, but not **what is allowed to participate**.

```text
question + uploaded corpus + candidate answer -> score
```

A top-k RAG pipeline can omit the one low-ranked page, slide, sheet, table, transcript segment, or exception that changes the score. ContextMesh instead turns the uploaded material into an addressable external context space and enforces 100% coverage before a final score is valid.

### Reality first

The project now keeps a public **Reality Lab** of current-main reproductions instead of asking users to trust the architecture:

- **Cognee 1.6.0** — the decisive source ranked 17 in two controlled CHUNKS probes; visible top-5 recalled 0/2 while full-coverage execution preserved both.
- **RAGFlow current main** — a tenant 32K context override resolved as the 128K provider catalog value on one composite-reference path; the saved candidate patch makes the same regression pass.
- **Dify current main** — an 11,343-byte instruction source was selected/read, but ordinary shell rendering hid its decisive middle span behind an 8 KiB head/tail budget.

These are specific mechanism tests, not global product rankings.

- [Reality Lab static surface](site/reality.html)
- [Evidence lifecycle contract](docs/EVIDENCE_LIFECYCLE.md)
- [External demand radar](docs/reality/EXTERNAL_DEMAND_RADAR.md)

The resulting diagnostic model follows evidence through:

```text
ingested -> stored -> retrieved -> eligible -> rendered -> model-visible -> judged
```

A source can therefore fail as a retrieval miss, an eligibility cutoff, or a transport/model-visibility loss without those states being collapsed into one “context missing” label.



## v0.15 — Reality Probe

ContextMesh now includes an executable falsification harness rather than assuming full coverage is useful.

The first scenarios are derived from public failure classes observed in Cognee issues: near-duplicate top-k crowding, unconditional nearest-neighbor context, unsupported assertions, and structured information loss. The included corpora are synthetic mechanism probes; they do not copy external user data.

Run the deterministic control against the real ContextMesh traversal path:

```bash
contextmesh reality-probe --format markdown
```

The default comparison is:

```text
lexical top-k
vs
ContextMesh full-coverage execution
```

The ContextMesh backend creates a real manifest and executes `ProgressiveEvaluator`; lexical ranking controls reading order but cannot remove a required document.

An optional Cognee integration uses the current Cognee Python `remember` + `SearchType.CHUNKS` path:

```bash
pip install -e '.[cognee]'
contextmesh reality-probe --backend cognee --backend contextmesh --top-k 5 --format markdown
```

A configured ContextMesh model route can be added with `--route-id` so every backend's selected evidence is judged by the same model. This separates retrieval failure from reasoning failure.

A first live external run has now been completed against **Cognee 1.6.0 / SearchType.CHUNKS / top_k=5**. In the two targeted controlled probes, Cognee returned chunks normally but recalled **0/2 decisive sources**, while ContextMesh preserved both under 100% coverage.

A deeper rank fetch then located both decisive sources at **rank 17**. ContextMesh did **not** rank them better — its scheduler also placed them at rank 17. The difference is eligibility: Cognee's visible top-5 omitted rank 17, while ContextMesh read it later because ranking cannot remove a required source. This is evidence for the blind-spot mechanism, not a claim that Cognee is globally worse or that every downstream LLM would answer incorrectly.

Saved results:
- [Cognee 1.6.0 reality result](docs/reality/Cognee-1.6.0-2026-09-24.md)
- [Rank-depth: rank 17 vs eligibility](docs/reality/Cognee-1.6.0-rank-depth-2026-09-24.md)

The same Reality Probe now also records byte-range visibility and a source-level evidence lifecycle trace, so “selected” is no longer treated as equivalent to “semantically visible.”

Additional current-main evidence:
- [Dify #42889 — selected source, hidden middle span](docs/reality/Dify-42889-2026-09-24.md)
- [RAGFlow #20140 — validated 32K vs 128K context-resolution delta](benchmarks/results/ragflow-20140-2026-09-24.json)

See [docs/V015_REALITY_PROBE.md](docs/V015_REALITY_PROBE.md) for methodology and limits, and [docs/EVIDENCE_LIFECYCLE.md](docs/EVIDENCE_LIFECYCLE.md) for the generalized stage model.

## v0.14 — resumable multipart uploads

Large uploads now use durable upload sessions instead of one all-or-nothing browser request.

```text
Browser
  -> create upload session
  -> upload only missing parts
  -> per-part SHA-256 (local backend)
  -> complete / verify
  -> durable ingest queue
```

The Workspace stores the upload-session ID in browser local storage, so reconnecting and pressing upload again resumes missing parts instead of re-sending confirmed parts.

Two transports are supported:

- `local` — durable part files + SQLite upload-session metadata. The server verifies each supplied part checksum and computes the final object SHA-256 while assembling.
- `s3` — native S3-compatible multipart upload using a server-created upload ID and presigned `UploadPart` URLs. Status recovery reconciles remote `ListParts`, then completion supplies ordered `PartNumber + ETag` entries. This also works with MinIO-compatible endpoints when configured.

```bash
# local durable staging
export CONTEXTMESH_UPLOAD_BACKEND=local

# S3 / MinIO
pip install -e '.[s3]'
export CONTEXTMESH_UPLOAD_BACKEND=s3
export CONTEXTMESH_S3_BUCKET=my-bucket
export CONTEXTMESH_S3_ENDPOINT_URL=http://minio:9000   # omit for AWS S3
export CONTEXTMESH_S3_REGION=us-east-1
```

New endpoints include `/api/upload-sessions`, part upload/presign/status/complete/abort operations, and `/api/ingest-jobs/from-upload-sessions`.

MinIO E2E is exercised in CI against a real temporary MinIO server: multipart creation, SigV4 presigned part uploads, `ListParts` resume reconciliation, completion, byte-for-byte download, and abort. AWS IAM/policy integration and multi-GB WAN stress remain separate production gates.

## v0.13 — durable execution queue

Long-running ingest and evaluation no longer depend on an in-process `ThreadPoolExecutor`. Jobs are written to a WAL-mode SQLite queue and leased atomically by workers.

```text
FastAPI submit
    |
    v
SQLite WAL durable queue
    |
    +--> worker A
    +--> worker B
    |
    v
checkpointed ingest / full-coverage evaluation
```

Worker leases have expiry/recovery semantics, retries are persisted, queued jobs can be cancelled before execution, and worker heartbeats are visible in Admin.

For local development, the web server starts one embedded worker by default. For production-style process isolation:

```bash
export CONTEXTMESH_EMBEDDED_WORKER=0
contextmesh serve --host 0.0.0.0 --port 8765

# separate process
contextmesh worker --data .contextmesh
```

`docker compose up --build` now starts the API/UI and a separate worker service sharing the same persistent data volume.

The SQLite queue is intentionally a **single-host** durable backend. It removes job loss on web-process restart and is suitable for one-machine multi-process deployments. Multi-node deployments should implement the same queue contract with Redis/NATS/Postgres rather than placing SQLite WAL on a network filesystem.

Admin exposes queue depth, running/failed/completed items, attempt counts, lease owners and active worker heartbeats.

## v0.12 — scalable block payload storage

ContextMesh now separates three runtime persistence roles:

```text
Manifest                  coverage authority
SQLite payload store      addressable ContextBlock bodies
SQLite/FTS catalog        navigation + scheduling index
```

New corpora use a WAL-mode SQLite payload store by default instead of writing one JSON file per block. This removes the small-file/inode bottleneck that appears when a corpus grows toward hundreds of thousands or millions of blocks. Legacy JSON-per-block corpora remain readable and can be lazily migrated without changing any manifest coverage IDs.

```bash
# default
export CONTEXTMESH_BLOCK_BACKEND=sqlite

# compatibility / portable JSON-per-block mode
export CONTEXTMESH_BLOCK_BACKEND=json
```

The Context Explorer now batches block reads, and page/slide/sheet/timeline co-location plus explicit source references use structural catalog indexes rather than scanning every block on every inspection. Search and relationship indexes still **never alter coverage eligibility**.

Measured local smoke benchmark (not a production SLA):

- 100,000 block payloads: ~1.50 s batched SQLite write
- 5 random block reads: ~0.63 ms total
- 100,000 catalog rows: ~1.96 s index build, ~1.62 ms FTS query (v0.11 benchmark)

Reproduce with `examples/storage_benchmark.py` and `examples/catalog_benchmark.py`.

## v0.11: typed evidence + scalable catalog

ContextMesh now separates the **raw evidence ledger**, **typed evidence state**, and **model-facing reduced state**. Relevant blocks produce source-linked atoms for claims, numbers, dates, exceptions, contradictions and requirements. The final judge receives this typed channel alongside hierarchical reductions, so critical values and exception clauses do not have to survive only as free-form summaries.

The portable filesystem store also gains a SQLite catalog with FTS5 acceleration:

```text
payload store = addressable block bodies
SQLite/FTS   = navigation + scheduling index
manifest     = coverage eligibility
```

Search can rank large address spaces without scanning every payload for each query, but it still **cannot remove any required block from execution**. Existing corpora are lazily backfilled into the catalog.

```text
GET /api/corpora/{corpus_id}/catalog
```

returns index backend, indexed block/asset counts, modalities and readiness.

Reproducible catalog benchmark:

```bash
PYTHONPATH=src python examples/catalog_benchmark.py --blocks 100000
```

See [`docs/V011_VALIDATION.md`](docs/V011_VALIDATION.md) for measured smoke results and limits.

## v0.9 large-job reliability

ContextMesh now treats a model route's context window as an execution constraint, not metadata. If a single addressable block plus the question/answer cannot fit, the block is exhaustively paged into route-sized slices; every slice must finish before the original block satisfies coverage. Hierarchical reduction is also budget-aware.

Operational UX now includes resumable checkpoints, cancel/resume, retryable ingest jobs, byte-level browser upload progress, scoped SSE streams, route health checks, per-route concurrency caps, request timeouts, and restart reconciliation. These controls reduce common failure modes when a corpus requires thousands of provider calls.

The remaining production-scale boundaries are deliberately separate: object storage/resumable multipart uploads, multi-node Redis/NATS/Postgres queue backends, multi-tenant auth/RBAC, and deeper provider-specific native video/audio validation.

## v0.7 in one picture

```text
PDF / PPTX / XLSX / DOC / MD / TXT / image / audio / video
                         |
                         v
              async file-level ingest queue
                         |
                  Docling / fallbacks
                         |
                         v
                 Canonical Corpus
        page / slide / sheet / timeline / section
                         |
                  Context Manifest
                         |
            priority scheduler (optional search)
                         |
               ALL required blocks
                         |
           parallel exhaustive inspection
                         |
          raw evidence + source provenance
                         |
           bounded hierarchical reduction
                         |
                         v
              cloud / local model route
                         |
                         v
              final score after 100%
```

The public client can submit **one evaluation job**. Internally ContextMesh performs as many bounded model reads as necessary. A single external API call does not mean one Transformer forward pass.

## Core invariants

```text
ranking = scheduling, not filtering
coverage < 100% => no valid final score
failed block != visited block
raw evidence != reduced model state
parallel completion order != reduction order
KV cache != context-window extension
```

## What v0.7 adds

- asynchronous file-level ingest queue
- SSE live progress for ingest and evaluation
- one-submit background full-coverage evaluation jobs
- PDF page Explorer fallback via `pypdf`
- PPTX slide Explorer fallback via `python-pptx`
- XLSX sheet/row-range Explorer fallback via `openpyxl`
- Docling adapter remains preferred for richer multimodal parsing
- generic timeline grouping when parser metadata includes timestamps
- boundary-safe neighbor context for model inspection without double-counting coverage
- persistent model routing center for cloud or local OpenAI-compatible endpoints
- route-level max-context metadata and token pricing
- per-job prompt/completion token, latency, cached-token and estimated-cost accounting when the provider returns usage
- LMCache/vLLM Prometheus telemetry dashboard
- LMCache token hit rate
- vLLM prefix-cache hit rate
- vLLM KV-cache usage
- average TTFT
- atomic checkpoint/control-plane writes for concurrent readers

Everything from previous releases remains: resumable checkpoints, deterministic parallel execution, failure ledger, bounded reduction tree, source-addressed ContextBlocks, evidence traceability, score-preservation benchmark, RLM tool bridge, and LMCache/vLLM serving hooks.

## How overflow is actually solved

ContextMesh does **not** claim to make a 128K model perform native full attention over 5M tokens.

For a corpus that does not fit:

```text
5M raw tokens
   |
   v
addressable blocks
   |
   +--> each required block is inspected
   |      + small previous/next boundary context
   |
   v
score-preserving evidence capsules
   |
   v
hierarchical reduction tree
   |
   v
bounded final context
```

All raw blocks remain stored and re-addressable. The final model does not receive 5M raw tokens simultaneously; it receives a bounded state produced after every required source block has participated in execution.

This is the only generally deployable approach when the corpus exceeds the model's physical context limit. See [`docs/FULL_COVERAGE.md`](docs/FULL_COVERAGE.md).

## Why KV / LMCache is still useful

KV caching does not solve overflow. It solves repeated computation.

For a fixed enterprise corpus evaluated against thousands of question/answer pairs, vLLM + LMCache can reuse compatible prefix/KV state and reduce prefill work. The portable asset is still the ContextMesh corpus; KV is model/runtime-specific compiled cache.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Rich media/documents:

```bash
pip install -e '.[dev,docling]'

Lightweight PDF/PPTX/XLSX fallbacks only:

```bash
pip install -e '.[dev,rich]'
```
```

## Run the web product

```bash
contextmesh serve --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/        Workspace
http://127.0.0.1:8765/admin   Admin
http://127.0.0.1:8765/docs    API docs
```

The Workspace provides upload, live ingest progress, page/slide/sheet/timeline Context Explorer, model-route selection, one-submit full-coverage evaluation, evidence ledger and score-drift calibration.

The Admin console provides ingest queue, corpus inventory, evaluation jobs, failures, model routing, token/cost/latency metrics and LMCache/vLLM cache telemetry.

## One-call evaluation API

```json
POST /api/evaluation-jobs
{
  "corpus_id": "corp_xxx",
  "question": "Does this answer comply with all uploaded evidence?",
  "answer": "...",
  "route_id": "local-qwen",
  "max_workers": 8,
  "retry_attempts": 2,
  "reduction_batch_size": 32
}
```

Returns immediately:

```json
{
  "accepted": true,
  "job_id": "job_xxx",
  "corpus_id": "corp_xxx",
  "events": "/api/events"
}
```

Subscribe to SSE `/api/events`, or read:

```text
GET /api/jobs/{corpus_id}/{job_id}
```

## Model routes

Routes can point to local vLLM/SGLang/Ollama-style OpenAI-compatible servers or cloud OpenAI-compatible endpoints. Secrets are referenced by environment-variable name rather than persisted.

```json
PUT /api/admin/model-routes/local-qwen
{
  "id": "local-qwen",
  "label": "Local Qwen",
  "provider": "openai-compatible",
  "base_url": "http://127.0.0.1:8000/v1",
  "model": "Qwen/Qwen3-32B",
  "enabled": true,
  "max_context_tokens": 131072,
  "input_cost_per_million": 0,
  "output_cost_per_million": 0
}
```

## LMCache / vLLM telemetry

```bash
export CONTEXTMESH_VLLM_METRICS_URL=http://127.0.0.1:8000/metrics
export CONTEXTMESH_LMCACHE_METRICS_URL=http://127.0.0.1:8080/metrics
```

ContextMesh reads Prometheus-compatible metrics directly; Prometheus/Grafana remain optional.

## Score-preservation benchmark

For small calibration corpora that fit in one direct request:

```text
Direct:      all raw source blocks -> one judge request
Progressive: all raw source blocks -> inspect -> reduce -> judge
```

`POST /benchmark` reports absolute score drift and a pass/fail tolerance gate. Use it before changing splitting, neighbor context, reduction fan-in, prompts, or judge models.

## Tests

```bash
PYTHONPATH=src pytest -q
```

v0.7 currently includes coverage, retry/resume, deterministic concurrency, benchmark, browser APIs, async jobs, control-plane persistence, metrics parsing, model routes, and native PDF/PPTX/XLSX Explorer tests.

## Current boundaries

- No engineering layer can make an API/model attend to more raw tokens in one forward pass than that model supports.
- Full coverage means every required source block participates in evaluation execution.
- Hierarchical reduction is still a representation transformation, so score equivalence must be benchmarked, not assumed.
- Rich audio/video semantic extraction depends on a capable parser/model pipeline; timeline grouping is used when timestamps are available.


## v0.9 fidelity verification

ContextMesh now separates three independent guarantees:

1. **Ingest coverage** — every submitted asset produced an ingest result.
2. **Semantic readiness** — known source channels (text, page visuals, formulas, native media, etc.) are addressable; unresolved channels block final scoring.
3. **Execution coverage** — every required ContextBlock was actually visited by the selected evaluator route.

Run an integrity audit after ingest:

```bash
contextmesh audit <corpus_id> --store .contextmesh/store
```

The audit checks required-block existence, empty textual blocks, media payloads, parent/sibling integrity, manifest counts, and asset reports. Source assets also record SHA-256 hashes so the ingest record can be tied back to the exact uploaded bytes.

Generate a real multi-format golden corpus for validation:

```bash
PYTHONPATH=src python examples/generate_fidelity_corpus.py ./fidelity-corpus
```

The generated set includes text, scanned PDF, PPTX, XLSX formulas/charts, DOCX, image, spoken WAV and MP4. After configuring a model route, run model-level needle recovery:

```bash
contextmesh fidelity-live <corpus_id> \
  --route-id <route> \
  --probe policy.txt=NEEDLE-TXT-8742 \
  --probe visual.png=NEEDLE-IMAGE-8742 \
  --probe scan.pdf=NEEDLE-IMAGE-8742 \
  --probe deck.pptx=NEEDLE-PPT-8742 \
  --probe book.xlsx=NEEDLE-XLSX-8742 \
  --probe report.docx=NEEDLE-DOCX-8742 \
  --probe speech.wav="needle audio eight seven four two"
```

A live probe inspects **all required blocks for the target asset**, not a top-k retrieval subset. Unsupported model modalities are reported as unsupported instead of silently passing. Generic OpenAI-compatible Chat Completions still has no portable raw-video schema, so raw video remains blocked unless a provider-specific video adapter is used.


## v0.10 UI

Workspace is now a three-pane operating surface:

- **Corpus** — upload, ingest progress, corpus readiness.
- **Context Explorer** — addressable page/slide/sheet/timeline/block browsing with source provenance.
- **Evaluation Inspector** — route preflight, question + candidate answer, full-coverage job progress, score and evidence.

Admin now includes a **provider-aware Model Routing Center**. Routes can target OpenAI, Anthropic, Gemini, Qwen, vLLM, SGLang, or a generic OpenAI-compatible endpoint. ContextMesh keeps the corpus portable; provider/model-specific caches remain disposable acceleration artifacts.

## Standalone repository deployment

ContextMesh is intended to live in its own repository and runtime boundary.

```bash
# local
pip install -e '.[dev,rich]'
contextmesh serve --host 127.0.0.1 --port 8765

# container
docker compose up --build
```

The repository includes:

- `.github/workflows/ci.yml` — Python regression tests.
- `.github/workflows/pages.yml` — optional static product/demo surface from `site/`.
- `Dockerfile` / `docker-compose.yml` — standalone API/UI runtime.
- `site/` — public static demo; never put provider keys there.
