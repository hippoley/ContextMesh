# Big Context Proof — NIST public corpus, Gates 1–2

**Date:** 2026-09-28  
**Evidence class:** real public corpus / reproducible proof preflight  
**Workflow run:** https://github.com/hippoley/ContextMesh/actions/runs/36373761033  
**Head:** `d158cb0dea241e6fc0aed97f984eb77e1ca36758`  
**Artifact:** `big-context-public-nist-preflight` · ID `10949814209`  
**Artifact ZIP SHA-256:** `40b2c1cce7fea75f5de3fea3146f4486574d67b60d9733a97b2c29ec7c4dde72`

This is the first ContextMesh Big Context Proof result that uses a real, publicly reproducible multi-file corpus rather than the synthetic Gate 0 execution contract.

It proves **Gate 1 (Corpus Reality)** and **Gate 2 (Ground-truth Matrix)** only.

It does **not** prove live-model evidence recovery, task accuracy, scale stability, or drift. Gates 3–5 remain unrun in this artifact.

## Corpus

The workflow downloaded 12 public NIST/AIRC source files at run time. No benchmark source document was vendored into the repository.

```text
12 assets
17,010,982 source bytes
3,882,513 conservative estimated tokens
131,072-token live-route context window
29.6212× corpus / model-context ratio
```

Format families:

```text
PDF      7
table    4  (CSV/XLSX)
text     1  (JSON)
```

The real ingest manifest contained:

```text
1,841 required coverage units

936 text
899 image
  6 table
```

Every submitted source had a SHA-256, ingest coverage was 100%, semantic coverage was 100%, and the corpus was coverage-ready.

### Gate 1

```text
status                 PASS
assets                 12
source hash coverage   100%
ingest coverage        100%
semantic coverage      100%
required blocks        1,841
corpus/context ratio   29.6212×
blockers               none
```

A ~29.6× corpus/context ratio here means **external corpus size**, not native single-forward-pass attention.

## Frozen benchmark matrix

The matrix was derived from actual ingested source units and then frozen into the workflow artifact.

For positive cases, the benchmark records source assets and exact target coverage-unit IDs. Those target IDs and expected answers are scorer-side ground truth; they are not intended to be exposed to the live model in Gate 3.

### Gate 2

```text
status       PASS
cases        132
needle kinds 11
modalities   text + table + image
blockers     none
```

Kind distribution:

| Kind | Cases |
| --- | ---: |
| exact | 15 |
| semantic-paraphrase | 15 |
| exception | 15 |
| table-cell | 15 |
| image-text | 12 |
| contradiction | 10 |
| cross-file | 10 |
| date | 10 |
| negative | 10 |
| number | 10 |
| supersession | 10 |

Position coverage:

```text
corpus: early 55 · middle 59 · late 18
local:  head 65 · middle 27 · tail 40
```

Modality cases:

```text
text   105
table   15
image   12
```

The image-text cases target real rendered PDF page images. Their scorer-side wording is paired from the corresponding text channel, so Gate 3 can test whether a vision-capable route recovers the source wording from the actual page image.

## Source integrity

The complete source SHA-256 values are persisted in:

`benchmarks/results/nist-public-gate1-2-2026-09-28.json`

The workflow also uploaded:

```text
download-manifest.json
corpus-manifest.json
gate1.json
gate2.json
needle-matrix.json
task-cases.json
```

The generated task set contains 33 candidate-answer tasks for Gate 3.


## Live cost preflight

The same successful public workflow also ran a **no-model-call cost preflight** for the first proposed live route:

```text
route                       qwen3-vl-8b-instruct
declared context            131,072 tokens
estimated input             89,344,074 tokens
estimated output             1,375,143 tokens
public Beijing input price   ¥0.5 / 1M tokens
public Beijing output price  ¥2 / 1M tokens
35% safety-factor estimate   ¥47.42
configured budget ceiling    ¥80.00
cost gate                    PASS
```

This is deliberately **not Gate 3**. It only establishes that the proposed first live fidelity run is bounded before any model call is made. Current model limits and list pricing are taken from Alibaba Cloud's official Model Studio page for `qwen3-vl-8b-instruct`.


## What this result proves

It establishes that ContextMesh can reproducibly ingest and address a real 12-file, 29.6212×-over-context corpus with source integrity and a sufficiently broad, exact-unit-grounded benchmark matrix.

It does **not** establish the product claim:

> “Give ContextMesh 10–30 files beyond the model window and it will still recover the right evidence and complete the task reliably.”

That claim still requires:

```text
Gate 3  live multimodal evidence recall + task accuracy + baselines — BLOCKED: provider credential missing
Gate 4  fixed-needle scale curve
Gate 5  repeated-run drift
```

The repository should continue to report the large-context task-success claim as **not yet proven** until those gates pass.

## Live readiness

A separate zero-provider-call workflow checked whether the repository can actually start Gate 3.

```text
workflow run               36374543342
DASHSCOPE_API_KEY          not configured
OPENAI_API_KEY             not configured
provider calls made        0
model tokens billed        0
Gate 3                     BLOCKED
```

This is an execution dependency rather than an algorithmic pass. The live workflow already enforces the cost ceiling before any provider call. Once an authorized provider secret exists, Gate 3 can be dispatched without another code change.

## Reproduce

```bash
python benchmarks/build_public_nist_proof.py \
  --workdir /tmp/contextmesh-nist-proof \
  --output-dir /tmp/contextmesh-nist-proof/results \
  --model-context-tokens 128000 \
  --min-corpus-ratio 5
```

The source list is pinned in:

`benchmarks/big-context/nist-public-corpus.json`

The release contract is defined in:

`docs/BIG_CONTEXT_PROOF.md`
