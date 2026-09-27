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
inspected
   ↓
authority
   ↓
reduced
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
| `authority-unresolved` | visible evidence remains contested or otherwise unresolved |
| `judge-failure` | evidence reached judgment but the judgment step failed |
| `none` | no loss detected in the measured lifecycle |

## Inspection is separate from model visibility

A model-facing payload can exist without a successful semantic inspection. ContextMesh now models:

```text
MODEL_VISIBLE
     ↓
INSPECTED
```

Successful and failed inspection transitions are persisted as hash-chained `TransitionReceipt` records. A failed model call does not silently count as semantic coverage.

## Reduction is a correctness boundary

Full source coverage can still be defeated after inspection if a free-form summary removes a decisive exception or unresolved conflict.

ContextMesh therefore treats reduction as an explicit transition:

```text
INSPECTED
    ↓
REDUCED
```

The v0.16 typed reducer is deliberately conservative: it merges only canonical duplicates, then validates the output with a monotonic reduction guard.

> **Compression may remove redundancy, but it must not silently remove epistemic diversity.**

Exceptions, contradictions, requirements, decisive evidence, and contested/unresolved authority cannot disappear without a valid preservation path.

Valid merges produce both a `ReductionReceipt` and a semantic `TransitionReceipt` with input IDs, output ID, provenance, evidence kind, and reducer policy/version.

## DecisionBundle

The final judge now receives a structured preservation channel in addition to legacy explanatory summaries:

```text
ContextBlock
  -> EvidenceAtom
  -> SemanticEvidenceUnit
  -> typed monotonic reduction
  -> DecisionBundle
  -> judge
```

`DecisionBundle` keeps claims, exceptions, contradictions, requirements, facts, and unresolved authority separate. Critical categories are rendered before ordinary claims/facts when the final decision-facing state must itself be bounded.

## ExecutionContract and multi-stage coverage

Finalization can now be governed by an explicit `ExecutionContract` rather than only `visited == all blocks`.

Current modes include `retrieval`, `hierarchical-summary`, `full-coverage`, `exhaustive-extraction`, and `authority-resolution`.

`CoverageSnapshot` tracks stage-specific coverage so the runtime can distinguish, for example, `model-visible=100%` from `inspected=98%` or `authority-resolved=96%`.

## Over-context execution contract

A synthetic executable benchmark now verifies the difference between corpus size and model-facing request size:

```text
12 files
~1,100,234 estimated corpus tokens
16,000 simulated model context tokens
68.765x corpus/window ratio

384 required blocks
384 inspected
coverage = 100%

max observed request = 12,652 chars
configured request budget = 64,000 chars

decisive exception survived into DecisionBundle = true
transition chain valid = true
```

See [Over-context execution contract](reality/Over-Context-1.1M-2026-09-27.md).

This does not prove native 1.1M-token attention or perfect real-model semantic recall. It proves a narrower execution property: a corpus can be much larger than the model-facing request budget while every required block still participates through bounded semantic execution.

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
3. **Eligibility integrity** — ranking/scheduling does not silently redefine required coverage.
4. **Visibility coverage** — required semantics remain model-visible.
5. **Inspection coverage** — required model-facing units were actually inspected.
6. **Authority integrity** — visibility is not mistaken for current truth.
7. **Reduction integrity** — redundancy may compress; epistemic diversity may not disappear silently.
8. **Judgment validity** — finalization occurs only when the active execution contract permits it.

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
- `docs/reality/Over-Context-1.1M-2026-09-27.md`

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
>
> model-visible is not inspected.
>
> compression may remove redundancy, not epistemic diversity.

ContextMesh should preserve conflicting history and make authority decisions inspectable rather than destructively hiding the losing side.
