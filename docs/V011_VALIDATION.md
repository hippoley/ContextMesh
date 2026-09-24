# ContextMesh v0.11 validation

v0.11 adds two preservation/scale layers without changing the core coverage contract:

1. **Typed evidence state** for source-linked claims, numbers, dates, exceptions, contradictions and requirements.
2. **SQLite/FTS Context Catalog** for indexed navigation/scheduling over large address spaces.

The manifest remains the authority for coverage eligibility. Search/index results can change order, never membership.

## Regression suite

```text
71 passed
```

The suite includes all prior v0.1-v0.10 coverage, retry/resume, multimodal fidelity, provider-adapter and UI/API tests plus v0.11 catalog/evidence tests.

## Catalog benchmark

Reproduce with:

```bash
PYTHONPATH=src python examples/catalog_benchmark.py --blocks 100000 --batch-size 5000
```

Observed in the current development container on 2026-09-24:

```text
100,000 ContextBlocks
batch index: ~1.96 s
FTS query:   ~1.62 ms
needle hits: 3 / 3
```

This is an engineering smoke benchmark, not a million-block production SLA. Filesystem/object-store behavior, hardware, text size, concurrency and WAL/storage configuration will materially affect results.

A second end-to-end smoke using `FileContextStore.put_blocks()` (which also writes portable block JSON) indexed 12,000 blocks in ~1.35 s and answered the same FTS needle query in ~0.77 ms in the same environment.

## Typed evidence checks

The test corpus includes:

- date: `2026-10-15`
- numeric SLA: `99.95%`
- exception: `Unless emergency maintenance...`
- requirement: `must remain...`
- contradiction/negation: `must not...` / `However...`

The full-coverage evaluator preserves these as typed atoms with source block IDs while retaining the original raw evidence note. Final model scoring receives both the reduced inspection state and a bounded typed-evidence channel.

## Scale boundary still remaining

The catalog removes repeated JSON scans from Explorer/search, but the default portable store still writes per-block JSON files. For multi-million-block production deployments, the next storage step is a configurable SQLite/Postgres/Parquet block payload backend plus object storage for media/raw assets.
