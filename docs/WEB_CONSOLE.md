# Web Console v0.7

## Workspace

1. Queue multiple files for ingestion.
2. Watch file-level ingest progress over SSE.
3. Mount the resulting corpus.
4. Browse the Context Explorer by PDF page, PPT slide, Excel sheet/row range, section, or media timeline locator when available.
5. Search the corpus for navigation; search never changes coverage eligibility.
6. Select a model route or the offline demo judge.
7. Submit one full-coverage evaluation job.
8. Watch live coverage, visited blocks, evidence and token usage.
9. Inspect the final score and evidence ledger only after coverage completes.
10. Run direct-vs-progressive score-preservation calibration on corpora that fit a direct request.

## Admin

The Admin console shows:

- file-level ingest queue and parser status
- corpus inventory
- full-coverage evaluation jobs
- failed blocks
- model route management
- aggregate prompt tokens, latency and estimated route cost
- LMCache hit rate
- vLLM prefix-cache hit rate
- KV-cache usage
- average TTFT
- runtime invariants and optional component availability

### Live metrics

Set either or both environment variables before starting ContextMesh:

```bash
export CONTEXTMESH_VLLM_METRICS_URL=http://127.0.0.1:8000/metrics
export CONTEXTMESH_LMCACHE_METRICS_URL=http://127.0.0.1:8080/metrics
```

The control plane parses Prometheus text and reports cache/token/latency telemetry without making Prometheus a hard dependency.

## Model routes

Routes store endpoint/model metadata and optional pricing. Secrets are referenced by environment-variable name rather than stored in the route object.

Example route:

```json
{
  "id": "local-qwen",
  "label": "Local Qwen",
  "provider": "openai-compatible",
  "base_url": "http://127.0.0.1:8000/v1",
  "model": "Qwen/Qwen3-32B",
  "api_key_env": null,
  "enabled": true,
  "max_context_tokens": 131072,
  "input_cost_per_million": 0,
  "output_cost_per_million": 0
}
```
