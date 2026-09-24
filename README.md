# ContextMesh

> v0.12: Full-Coverage Context Runtime with typed evidence preservation and a scalable SQLite/FTS context catalog.

**Full-coverage external context runtime for evaluating AI answers against corpora larger than a model context window.**

ContextMesh is not a RAG framework. Retrieval can decide **what is read first**, but not **what is allowed to participate**.

```text
question + uploaded corpus + candidate answer -> score
```

A top-k RAG pipeline can omit the one low-ranked page, slide, sheet, table, transcript segment, or exception that changes the score. ContextMesh instead turns the uploaded material into an addressable external context space and enforces 100% coverage before a final score is valid.



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

The remaining production-scale boundaries are deliberately separate: object storage/resumable multipart uploads, durable distributed workers, multi-tenant auth/RBAC, scalable metadata/search indexing, and provider-specific native video/audio adapters.

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
