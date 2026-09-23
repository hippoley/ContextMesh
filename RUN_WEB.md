# Run ContextMesh v0.7

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e .
contextmesh serve --host 127.0.0.1 --port 8765
```

Open:

- Workspace: http://127.0.0.1:8765/
- Admin: http://127.0.0.1:8765/admin
- API docs: http://127.0.0.1:8765/docs

For richer parsing:

```bash
python -m pip install -e '.[docling]'
# or lightweight office/PDF fallbacks:
python -m pip install -e '.[rich]'
```

ContextMesh also has lightweight local fallbacks for PDF (`pypdf`), PPTX (`python-pptx`) and XLSX (`openpyxl`) when those packages are installed.

## Live LMCache / vLLM metrics

```bash
export CONTEXTMESH_VLLM_METRICS_URL=http://127.0.0.1:8000/metrics
export CONTEXTMESH_LMCACHE_METRICS_URL=http://127.0.0.1:8080/metrics
```

## One-call full-coverage evaluation

```bash
curl -X POST http://127.0.0.1:8765/api/evaluation-jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "corpus_id":"corp_xxx",
    "question":"...",
    "answer":"...",
    "route_id":"local-qwen",
    "max_workers":8
  }'
```

The request returns a `job_id` immediately. Subscribe to `/api/events` for SSE progress or read `/api/jobs/{corpus_id}/{job_id}`.
