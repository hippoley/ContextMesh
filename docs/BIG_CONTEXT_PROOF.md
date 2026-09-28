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

A valid scale curve keeps the decisive evidence fixed and grows distractors around it.

It does **not** simply take the first 10%, 20%, 50% of a corpus, because that can remove the needle and turn scale into a different task.

Default requested points:

```text
1x
2x
5x
10x
20x
```

relative to the configured model context window.

Coverage units remain whole. A point may therefore execute at 2.1x rather than silently slicing a required block to manufacture exactly 2.0x.

The gate records:

- requested ratio;
- actual ratio;
- selected blocks/assets;
- evidence recall;
- term fidelity;
- negative accuracy;
- task accuracy;
- each baseline’s task accuracy.

Default release policy requires the curve to reach at least 20x and ContextMesh evidence recall to drop by no more than 5 percentage points from the first completed point.

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