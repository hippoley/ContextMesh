# Big Context Proof

ContextMesh does **not** treat “the runtime can traverse a corpus larger than one model window” as proof that large-context tasks are solved.

The existing ~1.1M estimated-token synthetic contract is **Gate 0**: it verifies execution shape, bounded requests, full required-block traversal, receipts, and preservation mechanics.

The product claim:

> “I can give ContextMesh 10–30 large files, far beyond the model context limit, and it can still recover decisive evidence and complete the task reliably.”

requires all five gates below.

## Gate 1 — Corpus Reality

A proof corpus must be a real ingested corpus, not one generated string split into many names.

Default release criteria:

- 10–30 source assets;
- source SHA-256 present for every asset;
- at least 3 file-format families;
- semantic coverage ready;
- conservative corpus/model-context ratio >= 5x.

Gate 1 intentionally uses a conservative one-character-per-token qualification estimate when no exact tokenizer replay is available. It is harder to pass for CJK/code/JSON rather than easier.

Workspace exposes this check through **Calibrate → Check Gate 1 readiness**.

## Gate 2 — Ground-truth Needle Matrix

The ground truth must be deep enough that one happy-path marker cannot certify the system.

Default criteria:

- at least 100 cases;
- at least 8 needle kinds;
- at least 2 modalities;
- early / middle / late corpus positions;
- head / middle / tail local positions;
- negative and cross-file cases;
- present cases point to actual assets in the ingested manifest;
- every case has explicit match terms.

Supported kinds:

```text
exact
semantic-paraphrase
number
date
exception
contradiction
supersession
cross-file
table-cell
image-text
negative
```

A schema-only example lives at:

```text
benchmarks/big-context/needle-matrix.example.json
```

The example is deliberately too small to pass Gate 2.

## Gate 3 — Evidence + Task + Baselines

Gate 3 runs a real configured model route.

Needle recovery does **not** tell ContextMesh which file contains the needle. Each case executes the normal full-coverage runtime over the whole projected corpus. Ground truth is used only after execution to score whether the relevant evidence was recovered.

Reported metrics are separate:

```text
Evidence Recall
Evidence Term Fidelity
Negative Accuracy
Task Accuracy
Unsupported / Blocked Cases
Cost
Latency
```

Built-in same-model baselines:

```text
lexical-top-5
lexical-top-20
direct-full-context
contextmesh-full-coverage
```

`direct-full-context` is a calibration baseline, not a license to send an oversized corpus to a provider. If its constructed single request exceeds the configured route token budget, ContextMesh must block it locally before network I/O; the live cost estimator relies on this zero-call contract.

The baseline interface is intentionally separate from the result schema so vector/MMR/agentic-search adapters can be added without redefining the proof report.

Default ContextMesh release thresholds:

```text
Evidence Recall          >= 0.90
Evidence Term Fidelity   >= 0.90
Negative Accuracy        >= 0.95
Task Accuracy            >= 0.90
Unsupported Cases        == 0
```

Task cases can carry tags such as `authority`, `modality`, or `contradiction`; the proof report preserves tag-level accuracy for drift analysis.

## Gate 4 — Scale Curve

Gate 4 has **two distinct states before a live result exists**:

```text
NOT PREPARED
    ↓
PREPARED
  frozen panel
  exact anchor set
  nested 1x/2x/5x/10x/20x projections
  stable projection fingerprints
  no model calls
    ↓
PASS or FAIL
  same frozen projections
  live model evidence-recall curve
```

**PREPARED is not PASS.** It proves the experiment is well formed; it does not prove model fidelity.

A valid scale curve keeps the decisive evidence fixed and grows distractors around it. It does **not** simply take the first 10%, 20%, 50% of a corpus, because that can remove the needle and turn scale into a different task.

Default requested points:

```text
1x
2x
5x
10x
20x
```

relative to the configured model context window.

Modern proof matrices freeze exact `target_block_ids`. Gate 4 therefore anchors the **smallest decisive coverage units**, not whole source files. Older matrices without block-level ground truth may fall back to asset-level anchors.

Distractors are added in a stable SHA-256 order rather than source order, so small scale points do not become accidental "early-corpus" samples. Every larger projection must be a strict superset of the previous one.

Coverage units remain whole. A point may therefore execute at 2.01x rather than silently slicing a required block to manufacture exactly 2.00x.

Before a live Gate 4 call, ContextMesh freezes:

- selected case IDs and kind/modality/position coverage;
- exact anchor block IDs and anchor fingerprint;
- block IDs for every scale point;
- actual ratio, selected assets, and modality counts;
- one SHA-256 projection fingerprint per point.

A live Gate 4 run can consume this frozen plan. Corpus mismatch, context-window mismatch, anchor drift, a missing ratio, or a projection fingerprint change is rejected **before model calls**.

The live gate records:

- requested and actual ratio;
- selected blocks/assets;
- evidence recall;
- retrieval-only evidence recall for `lexical-top-5` and `lexical-top-20` on the exact same frozen projection;
- evidence term fidelity;
- negative accuracy;
- optional task accuracy/baselines;
- cost and latency.

Default release policy requires the curve to reach at least 20x and ContextMesh evidence recall to drop by no more than 5 percentage points from the first completed point.

### Public NIST v2 preflight

The first strict public Gate 4 preflight exposed a real methodology failure instead of passing immediately.

In v1, a cross-file case pulled a table coverage unit large enough that the decisive anchor set reached **356,659 conservative tokens**, already larger than both the 65,536-token anchor budget and the 131,072-token live model context. That made a meaningful 1x point impossible.

The fix did **not** change source documents or delete the cross-file case. The ingest contract was tightened so table coverage units are bounded at **<=12,000 characters**, then the same 12-source NIST/AIRC corpus was re-ingested as `nist-public-big-context-v2`.

The frozen v2 preflight now has:

```text
panel               12 cases
anchor blocks        6
anchor tokens       28,589

requested    actual        blocks
1x           1.0054x          50
2x           2.0077x         109
5x           5.0084x         311
10x         10.0398x         662
20x         20.0009x       1,318
```

Every point preserves all anchors, is nested inside the next point, and has a committed projection fingerprint. The preflight made **0 provider calls**. The live recall curve remains unrun until Gate 3 passes and an authorized provider credential is available.

Evidence:

- `docs/reality/Big-Context-NIST-Gate4-Preflight-v2-2026-09-28.md`
- `benchmarks/results/nist-public-gate4-preflight-v2-2026-09-28.json`

## Gate 5 — Drift

One successful live run is not a drift proof.

Gate 5 requires a stored reference snapshot and at least one repeated candidate run. The snapshot fingerprints:

```text
route
model
model version
prompt version
chunk policy
reducer policy
metadata
```

Quality drift has default hard limits:

```text
Evidence Recall drop       <= 5 pp
Task Accuracy drop         <= 5 pp
Authority Accuracy drop    <= 2 pp
Negative Accuracy drop     <= 2 pp
```

Cost and latency ratios are always recorded. They become hard blockers only when an explicit operational threshold is configured.

### Promotion contract

A repeated run can also produce a separate release decision:

```text
PROMOTE
HOLD
REJECT
```

This decision does not replace Gate 5. Gate 5 answers whether the candidate is within drift limits; the promotion contract answers whether it should replace the current reference under explicit operational policy.

Default workflow promotion constraints are:

```text
Gate 5 status                    PASS
20x ContextMesh recall drop      <= 5 pp
candidate/reference cost ratio   <= 1.25x
candidate/reference latency      <= 1.25x
```

Missing comparability or unavailable operational ratios produce `HOLD`, not `PROMOTE`.

## Run the proof

First live run:

```bash
python benchmarks/big_context_proof.py corp_xxx \
  --route-id my-live-route \
  --needles benchmarks/my-needle-matrix.json \
  --tasks benchmarks/my-task-cases.json \
  --output benchmarks/results/big-context-run-001.json \
  --snapshot-output benchmarks/results/big-context-run-001.snapshot.json
```

This can pass Gates 1–4 but will still print:

```text
BIG_CONTEXT_PROOF_NOT_YET_PROVEN
```

because Gate 5 needs a repeated run.

Repeat after a model/prompt/chunk/reducer change:

```bash
python benchmarks/big_context_proof.py corp_xxx \
  --route-id my-live-route \
  --needles benchmarks/my-needle-matrix.json \
  --tasks benchmarks/my-task-cases.json \
  --drift-reference benchmarks/results/big-context-run-001.snapshot.json \
  --output benchmarks/results/big-context-run-002.json \
  --require-all-gates
```

Only when all five gates pass does the report set:

```json
{
  "claim_proven": true
}
```

## What remains unproven today

The repository now contains the execution contracts, scoring harness, scale projection, drift model, and Workspace Gate 1 readiness check.

It does **not** yet contain a committed five-gate result from a real 10–30-file corpus and a real model route.

Until that artifact exists, the correct claim is:

> ContextMesh has the machinery required to test large-corpus semantic fidelity. The large-context task-success claim itself is not yet proven.