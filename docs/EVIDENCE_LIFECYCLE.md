# Evidence Lifecycle

ContextMesh treats evidence coverage as a lifecycle rather than a single retrieval score.

A source can be present in the corpus and still become unusable later. The runtime therefore distinguishes these stages:

```text
ingested
   ↓
stored
   ↓
retrieved
   ↓
eligible
   ↓
rendered
   ↓
model-visible
   ↓
judged
```

## Why a single coverage percentage is not enough

Three externally reproduced failures illustrate different loss stages.

### 1. Eligibility loss — Cognee CHUNKS

A decisive source existed in the deeper retrieval ranking at rank 17, but a visible top-5 cutoff removed it from downstream evidence.

The source was:

- ingested;
- stored;
- retrieved/ranked;
- **not eligible after the cutoff**.

This is not the same as a retrieval miss.

### 2. Transport visibility loss — Dify Agent V2

A large `SKILL.md` was successfully selected and read. The ordinary shell observation exposed only the first 4 KiB and last 4 KiB, hiding a decisive instruction in the middle.

The source was:

- ingested;
- stored;
- retrieved/selected;
- eligible;
- **rendered partially**;
- **semantically incomplete in model-visible context**.

A source-level selected flag would incorrectly report success.

### 3. Execution-contract drift — RAGFlow

The same two-part model reference resolved through different instance semantics across credential and context-length paths. A tenant-specific 32K override fell through to a 128K provider catalog value.

This is not a per-document evidence loss. It is an execution-contract failure that changes how much evidence the runtime believes can fit.

## Runtime model

`src/contextmesh/diagnostics.py` defines:

- `EvidenceStage`
- `EvidenceDisposition`
- `EvidenceFailureClass`
- `EvidenceStageRecord`
- `EvidenceLifecycleTrace`

Current failure classes include:

| Failure class | Meaning |
| --- | --- |
| `ingest-loss` | source never became reliably addressable |
| `retrieval-miss` | source is absent from the measured ranking/candidate output |
| `eligibility-loss` | source was ranked/found but policy removed it before downstream use |
| `transport-visibility-loss` | source was selected but rendering/truncation removed required semantics |
| `judge-failure` | evidence reached judgment but the judgment step failed |
| `none` | no loss detected in the measured lifecycle |

## Byte-range visibility

For transports that expose only part of a source, the trace can record:

```json
{
  "source_bytes": 11343,
  "visible_bytes": 8192,
  "visible_ratio": 0.722,
  "visible_byte_ranges": [
    [0, 4096],
    [7247, 11343]
  ]
}
```

This is intentionally more precise than a boolean `truncated=true`.

It lets a verifier ask whether a decisive marker, clause, row, page region or other semantic unit actually survived into the model-visible payload.

## Core invariants

ContextMesh currently treats the following as separate invariants:

1. **Ingest coverage** — every submitted asset has an ingest result.
2. **Semantic readiness** — known semantic channels are addressable and unresolved loss is explicit.
3. **Execution coverage** — every required ContextBlock is visited by a capable route.
4. **Visibility coverage** — the bytes/spans required by the evidence contract remain model-visible.
5. **Judgment validity** — a final score is not promoted from an incomplete or failed evidence path.

The fourth invariant is newer than the original full-coverage model and was added because external reality testing showed that a source can be “visited” while its decisive semantics are still missing.

## Diagnostic design principle

Prefer a stage trace over a single terminal label.

For example:

```text
source A:
  retrieved rank=17
  eligible=false
  first_loss=eligible
  failure=eligibility-loss

source B:
  retrieved rank=1
  eligible=true
  rendered=true
  visible=72%
  decisive_semantics=false
  first_loss=model-visible
  failure=transport-visibility-loss
```

That distinction changes the remedy:

- retrieval miss → improve retrieval/indexing;
- eligibility loss → inspect cutoff/reranker/filter policy;
- transport visibility loss → change rendering/pagination/tool contract;
- judge failure → change model/prompt/parser or abstain.

## Evidence, not certification

The current external probes are controlled reproductions of specific mechanisms. They are not product rankings or certifications.

Saved evidence:

- `docs/reality/Cognee-1.6.0-rank-depth-2026-09-24.md`
- `docs/reality/Dify-42889-2026-09-24.md`
- `benchmarks/results/ragflow-20140-2026-09-24.json`

Public surface:

- `site/reality.html`


## Authority

Evidence can survive every transport stage and still be unsafe to treat as current truth.

The authority stage records lifecycle facts such as:

- active
- contested
- superseded
- refuted
- expired
- verified / unverified
- validity interval

A contested fact can therefore be present end-to-end while authority remains unresolved:

```text
ingested      present
stored        present
retrieved     present
model-visible present
authority     unresolved
```

That is not retrieval loss. The model may have both sides of a conflict and still need an explicit policy for which fact is authoritative now.

This stage was added after a live Mem0 2.2.0 probe preserved both a verified active database-port fact and a newer contested transient observation. Default semantic search returned both with close scores; an explicit lifecycle filter excluded the contested fact.

See [the Mem0 2.2.0 temporal-authority result](reality/Mem0-2.2.0-temporal-authority-2026-09-24.md).

The narrow invariant is:

> visibility is not authority.

ContextMesh should preserve conflicting history and make authority decisions inspectable rather than destructively hiding the losing side.
