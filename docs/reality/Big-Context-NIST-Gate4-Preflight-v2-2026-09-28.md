# Big Context Proof — NIST Gate 4 preflight v2

**Date:** 2026-09-28  
**Status:** **PREPARED — live Gate 4 not run**  
**Official corpus:** `nist-public-big-context-v2`  
**Reference public proof run:** https://github.com/hippoley/ContextMesh/actions/runs/36393959366

This is the official Gate 4 experiment definition for ContextMesh. It replaces the earlier v1 scale plan.

## Why v2 exists

The original NIST ingest left a small number of table coverage units extremely large. A strict cross-file candidate required:

```text
356,659 conservative anchor tokens
```

which already exceeded the 131,072-token live route context before distractors were added.

The fix did **not** remove the hard cross-file case and did not change any source file. The same 12 NIST/AIRC sources were re-ingested with:

```text
max_table_block_chars = 12,000
```

Result:

```text
v1 required blocks              1,841
v1 max table block chars      356,080
v1 blocks > model context            2

v2 required blocks              1,905
v2 max table block chars       11,999
v2 blocks > 12,000 chars            0
v2 blocks > model context           0
```

Gate 1 and Gate 2 remain PASS on the same source SHA set.

## Strict frozen panel

The v2 panel is intentionally small because Gate 4 measures scale sensitivity, while Gate 3 remains the broad 132-case fidelity test.

```text
cases                         12
kinds                         11
modalities                    text + table + image
cross-file case               present
local positions               head + middle + tail
anchor blocks                 6
anchor tokens            28,589
anchor budget            65,536
```

Frozen case IDs:

```text
negative-000
cross-file-008
table-002
image-text-000
contradiction-003
exact-003
number-003
semantic-003
supersession-003
date-003
exception-003
exact-011
```

Anchor fingerprint:

`0bfca9893c23963f516b62021ecec9efecb0c218e40291456c110034e47d2499`

## Frozen nested projections

Every larger projection is a strict superset of the previous one. The same six exact decisive anchor units remain present at every scale.

| Requested | Actual | Est. tokens | Blocks | Assets | Image / Table / Text | Projection fingerprint |
| ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1× | 1.0054× | 131,784 | 50 | 11 | 19 / 4 / 27 | `2afa4ed8d60f…e1346b1ea8d` |
| 2× | 2.0077× | 263,159 | 109 | 12 | 42 / 6 / 61 | `f7ea6c42f7d3…6015c6b7b1` |
| 5× | 5.0084× | 656,467 | 311 | 12 | 132 / 10 / 169 | `8b55061fe469…aa3d2bd7` |
| 10× | 10.0398× | 1,315,932 | 662 | 12 | 312 / 24 / 326 | `ed955fa68254…9d7ed9a7bf6` |
| 20× | 20.0009× | 2,621,558 | 1,318 | 12 | 619 / 47 / 652 | `b7ea4ff0a131…9e1664d` |

The live Gate 4 executor accepts the frozen plan and verifies corpus ID, context window, exact anchor set, and projection fingerprints before provider calls. A changed or tampered projection is rejected locally.

Distractors use a stable SHA-256 order rather than source order, reducing early-corpus bias while preserving nested projections.

## Cost envelope

Current conservative no-call estimate:

```text
Gate 3 only                 ¥47.42
Gate 3 + Gate 4             ¥57.17
35% safety factor           included
provider calls in preflight 0
```

This is an architecture-level estimate, not a provider invoice.

## Release condition

This artifact is **not Gate 4 PASS**.

The live curve must execute the exact frozen projections and report for every point:

```text
evidence recall
evidence term fidelity
negative accuracy
unsupported blocks
latency
token usage / estimated cost
```

Gate 4 passes only if:

```text
highest completed scale        >= 20×
evidence recall at each point  >= 0.90
recall drop                    <= 5 percentage points
anchor preservation            true
projection fingerprints        exact match
failures                       retained and reported
```

Current status:

> **Gate 4 PREPARED — strict experiment frozen and auditable; live scale fidelity not yet proven.**

Machine-readable artifact:

`benchmarks/results/nist-public-gate4-preflight-v2-2026-09-28.json`
