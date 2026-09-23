# ContextMesh remaining production gaps after v0.9

## P0 — directly affects team usability or correctness

1. **Durable distributed jobs** — the current worker pool is in-process. v0.9 marks stale work `interrupted` and makes it resumable, but Redis/NATS + durable workers are required for multi-instance production.
2. **Object storage + resumable multipart upload** — local disk works for one node; multi-GB team uploads need S3/MinIO, pause/resume, dedupe and server-side checksums.
3. **Scalable block catalog/search** — filesystem JSON is portable but browsing/searching hundreds of thousands or millions of blocks needs SQLite/Postgres metadata plus FTS/BM25 (and optional vector navigation). Retrieval must remain scheduling-only.
4. **Auth/RBAC/multi-tenancy** — corpus, route and event access are currently shared by the server process. Team deployment needs tenant/workspace IDs, ACLs and audit trails.
5. **Native provider adapters** — generic OpenAI-compatible transport covers text/table/vision and some audio, but portable raw-video semantics do not exist. Add Gemini native video, provider-specific audio, and local Qwen-Omni/video adapters.
6. **Structured evidence state** — reducers still exchange compact text notes. For stronger score preservation, promote claims, numbers, exceptions, contradictions and provenance into typed evidence objects, and rehydrate raw spans when reductions are uncertain.
7. **Real-model fidelity matrix** — parser/integrity fixtures are green, but cloud/local multimodal needle recall and score drift need continuous benchmarks per route/model version.

## P1 — scale, cost and operations

- RPM/TPM-aware route scheduler, provider 429 backoff and queue fairness.
- Per-job token/cost/time budgets with pause-before-overrun.
- Incremental corpus versions: re-ingest only changed assets/blocks and reuse valid evidence/KV caches.
- Malware/archive-bomb scanning and parser sandboxing for untrusted uploads.
- OpenTelemetry traces and persistent Prometheus/Grafana dashboards.
- Provider file/context-cache handles to avoid repeatedly transferring stable cloud-side corpus material.
