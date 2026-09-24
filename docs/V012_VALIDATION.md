# ContextMesh v0.12 validation

v0.12 targets the next scale bottleneck after the v0.11 FTS catalog: ContextBlock payload storage.

## Regression

```bash
PYTHONPATH=src pytest -q
```

Expected for this release: **76 tests passed**.

Additional syntax checks:

```bash
python -m compileall -q src/contextmesh
node --check src/contextmesh/web/contextmesh.js
```

## Storage contract

Three roles are now deliberately separate:

```text
CorpusManifest          coverage authority / eligibility
SQLiteBlockPayloadStore addressable ContextBlock payloads
SQLiteContextCatalog    navigation, structural lookup, scheduling rank
```

The payload backend cannot remove blocks from coverage. The catalog cannot remove blocks from coverage. Only the manifest defines the required coverage set.

## Backward compatibility

The default runtime backend is `sqlite`. A v0.1-v0.11 corpus that still has `corpus/blocks/*.json` can be opened by v0.12. Missing SQLite payloads are copied from the legacy JSON files in batches; IDs and manifest coverage are unchanged.

Set `CONTEXTMESH_BLOCK_BACKEND=json` to keep the old JSON-per-block runtime backend.

## 100K payload smoke benchmark

Command:

```bash
PYTHONPATH=src python examples/storage_benchmark.py --blocks 100000 --batch-size 5000
```

Measured in the development container:

```text
blocks:                  100,000
SQLite batched write:    ~1.50 s
write throughput:        ~66.5K blocks/s
5 random reads:          ~0.63 ms total
probe hits:              5 / 5
database size:           ~50.0 MB
```

This benchmark exercises the payload backend only. It excludes parser time, model calls, media storage, and network I/O. It is **not** a million-block production SLA.

## Structural lookup

v0.12 also removes an important O(N²) path from runtime inspection. `related()` and explicit source `references()` now use indexed source locators for:

- PDF page
- PPT slide
- Excel sheet/workbook page
- overlapping media timeline intervals

The portable scan implementation remains as a fallback for custom stores.

## Remaining production boundary

SQLite is appropriate for a single-node runtime. A distributed deployment with many ingest/evaluation workers should move payloads/catalog metadata to Postgres/Parquet/object-storage backed infrastructure while preserving the same store contract. Raw large media still belongs in S3/MinIO rather than SQLite.
