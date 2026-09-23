# ContextMesh Architecture v0.7

## Goal

Create a portable external context layer for evaluation workloads where the uploaded corpus is itself part of the evaluation input and may exceed the target model's context window by orders of magnitude.

## Planes

```text
DATA PLANE
  raw uploads
  canonical corpus
  addressable ContextBlocks
  source provenance

CONTEXT PLANE
  coverage manifest
  page / slide / sheet / timeline addressing
  navigation/search
  exhaustive scheduler
  neighbor boundary context
  evidence ledger
  bounded reduction tree

MODEL PLANE
  route registry
  cloud OpenAI-compatible APIs
  local vLLM / SGLang / compatible servers
  LMCache / prefix cache below serving layer

CONTROL PLANE
  ingest queue
  evaluation jobs
  SSE progress
  failures / retry
  score-preservation benchmark
  cache/token/latency/cost telemetry
```

## Overflow execution

```text
corpus_id
   |
   v
Coverage Manifest ----> N required blocks
   |
   v
priority order (search/vector optional)
   |
   v
N/N exhaustive inspections
   |
   +--> each primary block may carry small prev/next context
   |
   +--> raw evidence ledger with source locator
   |
   v
Reduction fan-in K
   |
level 1 summaries
   |
level 2 summaries
   |
...
   |
final bounded state
   |
final judge
```

Search can reorder the N blocks but cannot reduce N.

## Address space

A ContextBlock has:

- stable ID
- source asset
- modality/kind
- exact locator
- parent/children
- previous/next sibling
- textual/structured representation
- processable flag

Examples:

```text
PDF:   {page: 14, page_char_start: ..., page_char_end: ...}
PPTX:  {slide: 7, ...}
XLSX:  {sheet_name: "Revenue", row_start: 301, row_end: 600}
Video: {start_time: ..., end_time: ...}  # when parser provides timeline metadata
```

Structural nodes are navigational only. Required leaf blocks define the coverage contract.

## Cache boundary

```text
Portable:
  raw corpus
  ContextBlock graph
  evidence / checkpoints

Model-specific disposable acceleration:
  tokenizer products
  prefix/KV cache
  LMCache objects
```

KV state is never treated as the source of truth.

## Consistency

Background jobs and UI readers access the same filesystem control plane. JSON state is written atomically using temporary files + `os.replace` so a reader cannot observe a partially-written checkpoint.

## Production replacements

The v0.7 reference implementation intentionally uses lightweight components:

```text
filesystem store  -> object store + Postgres/metadata DB
ThreadPoolExecutor -> Celery/RQ/Temporal/Kubernetes jobs
in-process EventBus -> Redis Streams/NATS/Kafka
SSE -> SSE/WebSocket gateway
simple metrics fetch -> Prometheus + Grafana/OTel
```

These can be swapped without changing the core coverage semantics.
