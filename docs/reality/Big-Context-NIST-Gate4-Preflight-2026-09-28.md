# Big Context Proof — NIST Gate 4 preflight

**Date:** 2026-09-28  
**Status:** **PREPARED — live Gate 4 not run**  
**Public proof run:** https://github.com/hippoley/ContextMesh/actions/runs/36390126287  
**Artifact ID:** `10955907844`  
**Artifact ZIP SHA-256:** `d75417edf36302b63d8d7d90efb9d7858ba0ee5a32b52c52fa8bb4c3f4b510`

This artifact freezes the scale experiment that will be used by the live Gate 4 run.

It proves that the experiment is well-formed, nested, anchor-preserving, and cost-bounded.

It does **not** prove that evidence recall remains stable with scale. No live-model recall curve has run yet.

## Why the first Gate 4 plan was rejected

The first real NIST scale-plan attempt used a 24-case aggregate panel.

That run exposed a real experimental-design failure:

```text
anchor blocks       16
anchor tokens       422,455
model context       131,072
anchor/context      3.223×
```

Therefore the 1× and 2× points were impossible before adding even one distractor.

The preflight correctly failed:

```text
1×  BLOCKED
2×  BLOCKED
5×  available
10× available
20× available
```

The failed run is retained as evidence:

https://github.com/hippoley/ContextMesh/actions/runs/36389212996

The fix was not to relax 1×/2×. Gate 4 was redefined as a **small frozen scale-sensitivity panel**, while Gate 3 remains responsible for broad 132-case fidelity.

## Frozen panel

The accepted panel contains 12 cases.

```text
kind coverage       10 kinds
modalities          text + table + image
corpus positions    early + middle + late
negative cases      1
max cases / kind    2
```

Selected cases:

```text
negative-000
image-text-000
table-001
exception-012
date-003
supersession-009
number-008
contradiction-000
exact-000
semantic-000
contradiction-008
exact-008
```

Kind distribution:

```text
contradiction       2
exact               2
date                1
exception           1
image-text          1
negative            1
number              1
semantic-paraphrase 1
supersession        1
table-cell          1
```

Modality distribution:

```text
text  10
table  1
image  1
```

Corpus-position distribution:

```text
early   3
middle  8
late    1
```

The scale-panel anchor budget is 50% of one model context:

```text
model context       131,072
anchor budget        65,536
actual anchor cost   25,527
anchor blocks             7
```

This leaves most of the 1× point available for distractors.

Anchor fingerprint:

`fc56c2c289a42e6595152f9c7167bb950e4cb59d1c2f69f6a9d17b2ee1da5e4d`

## Frozen nested projections

Every larger point is a strict superset of the previous point. The same seven decisive anchor units remain present at every scale.

| Requested | Actual | Est. tokens | Blocks | Assets | Image / Table / Text | Projection fingerprint |
| ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1× | 1.0095× | 132,314 | 72 | 7 | 29 / 1 / 42 | `530792a7576e…c7888b` |
| 2× | 2.0258× | 265,521 | 128 | 10 | 55 / 2 / 71 | `672591bf4315…40d63` |
| 5× | 5.0191× | 657,865 | 148 | 11 | 63 / 3 / 82 | `5c527909ba15…c5344` |
| 10× | 10.0201× | 1,313,350 | 331 | 12 | 150 / 4 / 177 | `e31bfaa15691…0f5a7` |
| 20× | 20.0271× | 2,624,988 | 1,082 | 12 | 524 / 4 / 554 | `e7620f708c71…583b` |

The live Gate 4 executor can consume this frozen plan directly and verifies corpus ID, context size, anchor set, and projection fingerprints **before model calls**. A tampered projection is rejected locally.

Distractors use a stable hash order rather than source order, reducing early-corpus sampling bias.

## Cost envelope

Using the same conservative pricing assumptions already used for the proposed first live route:

```text
Gate 3 only                 ¥47.42
Gate 3 + Gate 4             ¥57.17
35% safety factor           included
Gate 4 input component      12,634,323 tokens
Gate 4 output component        450,816 tokens
provider calls in preflight          0
```

This is an architecture-level estimate, not a provider invoice.

## What remains required for Gate 4 PASS

Gate 4 remains **NOT RUN**.

The live curve can only be evaluated after Gate 3 passes. It must execute the exact frozen projections above and report, at each point:

```text
evidence recall
evidence term fidelity
negative accuracy
unsupported blocks
latency
cost
```

The release condition remains:

```text
reach >= 20×
evidence recall >= 0.90 at each required point
recall drop from first completed point <= 5 percentage points
```

Until those live results exist, the correct status is:

> **Gate 4 PREPARED — experiment frozen and auditable; scale fidelity not yet proven.**

Machine-readable result:

`benchmarks/results/nist-public-gate4-preflight-2026-09-28.json`