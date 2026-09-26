# Run ContextMesh v0.15.0

ContextMesh has two web surfaces:

1. **Runtime Workspace** — served by the FastAPI application and backed by live ContextMesh APIs.
2. **Public Reality Lab** — a static evidence surface intended for GitHub Pages.

They are intentionally separate. The Runtime Workspace should not be treated as a static demo.

## Local runtime

Create an environment and install the project:

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e '.[dev,rich]'
```

Start the API + embedded development worker:

```bash
contextmesh serve --host 127.0.0.1 --port 8765
```

Open:

```text
Workspace  http://127.0.0.1:8765/
Admin      http://127.0.0.1:8765/admin
API docs   http://127.0.0.1:8765/docs
```

The Admin and Workspace surfaces depend on live `/api/**`, job, SSE, storage, and model-route endpoints. They are not standalone static pages.

## Parsing options

The `rich` extra provides lightweight PDF / Office fallbacks used by the normal developer setup.

For Docling-backed parsing where supported:

```bash
python -m pip install -e '.[docling]'
```

ContextMesh also supports optional native/local parsing paths for formats such as PDF, PPTX, XLSX, DOCX, image, audio, and video depending on installed dependencies and configured model routes.

## One-submit full-coverage evaluation

Create an evaluation job:

```bash
curl -X POST http://127.0.0.1:8765/api/evaluation-jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "corpus_id": "corp_xxx",
    "question": "Does this answer comply with all uploaded evidence?",
    "answer": "...",
    "route_id": "local-qwen",
    "max_workers": 8,
    "retry_attempts": 2,
    "reduction_batch_size": 32
  }'
```

The API returns a job identifier while the durable execution path performs bounded reads, evidence extraction, reduction, and finalization.

Use the Workspace/Admin views or API job endpoints for progress and results.

## Durable worker mode

Development mode starts an embedded worker by default.

For process isolation:

```bash
export CONTEXTMESH_DATA=.contextmesh
export CONTEXTMESH_EMBEDDED_WORKER=0

# process 1
contextmesh serve --host 127.0.0.1 --port 8765

# process 2
contextmesh worker \
  --data .contextmesh \
  --poll-seconds 0.25 \
  --lease-seconds 180
```

The current SQLite/WAL queue is a **single-host** design. Do not treat a shared NFS/network-mounted SQLite database as a supported multi-node queue.

A Redis/NATS/Postgres-class multi-node queue backend remains outside the current production boundary.

## S3 / MinIO resumable uploads

Install the storage extra:

```bash
python -m pip install -e '.[dev,rich,s3]'
```

Typical configuration:

```bash
export CONTEXTMESH_S3_BUCKET=contextmesh
export CONTEXTMESH_S3_ENDPOINT_URL=http://127.0.0.1:9000
export CONTEXTMESH_S3_REGION=us-east-1
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
```

The repository CI includes a pinned MinIO end-to-end path. That test environment is not a production object-storage security configuration.

## Model-route telemetry

Optional vLLM / LMCache Prometheus endpoints:

```bash
export CONTEXTMESH_VLLM_METRICS_URL=http://127.0.0.1:8000/metrics
export CONTEXTMESH_LMCACHE_METRICS_URL=http://127.0.0.1:8080/metrics
```

Provider/model credentials should stay server-side. See [SECURITY.md](SECURITY.md) before evaluating sensitive corpora with remote model routes.

## Reality Probe

Run the deterministic control:

```bash
contextmesh reality-probe --format markdown
```

The default comparison is:

```text
lexical top-k
vs
ContextMesh full-coverage execution
```

For the optional Cognee backend:

```bash
python -m pip install -e '.[dev,cognee]'

contextmesh reality-probe \
  --backend cognee \
  --backend contextmesh \
  --top-k 5 \
  --format markdown
```

Verified external results and falsification cases are indexed in:

- [Reality Probe Index](docs/reality/README.md)
- [Evidence Lifecycle](docs/EVIDENCE_LIFECYCLE.md)

## Public Reality Lab

The public site is a static evidence surface built from:

```text
site/reality.html
benchmarks/results/**
scripts/build_reality_manifest.py
```

The Pages build intentionally publishes `site/reality.html` as the public root rather than publishing the backend-dependent Runtime Workspace.

After the one-time GitHub Pages setting is enabled with **Source = GitHub Actions**, the expected URL is:

```text
https://hippoley.github.io/ContextMesh/
```

Each public build generates `reality-data.json` from machine-readable benchmark results and includes SHA-256 provenance for the source artifacts.

## Containerized local stack

```bash
docker compose up --build
```

This is a local/development topology. Review [SECURITY.md](SECURITY.md) before exposing any ContextMesh service to an untrusted network.

## Health checks before publishing changes

The standard CI now covers:

```text
Python 3.11
Python 3.12
MinIO E2E
repository-integrity
```

The repository-integrity job validates:

- Public Reality Lab structure;
- evidence-manifest generation;
- source-artifact provenance;
- public/internal links;
- social-preview dimensions;
- separation between public Pages and backend-only runtime navigation.
