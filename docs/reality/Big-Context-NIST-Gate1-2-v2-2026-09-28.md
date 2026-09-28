# Big Context Proof — NIST public corpus v2, Gates 1–2

**Date:** 2026-09-28  
**Status:** **Gate 1 PASS · Gate 2 PASS**  
**Corpus:** `nist-public-big-context-v2`  
**Reference run:** https://github.com/hippoley/ContextMesh/actions/runs/36395147919  
**Artifact ID:** `10958350568`  
**Artifact ZIP SHA-256:** `909bda0123a6776ead4ded011abde6db7e727d4a1e6108610cf8032b1fd7ed86`

This is the official bounded-coverage-unit version of the public NIST proof corpus. It uses the same 12 source files and the same source SHA set as v1.

## Corpus

```text
12 real NIST/AIRC files
17,010,982 source bytes
3,882,513 conservative estimated tokens
131,072-token live route context
29.6212× corpus/context ratio
1,905 required coverage units
```

Modalities:

```text
text   936
image  899
table   70
```

All source hashes, ingest coverage, and semantic coverage are complete.

The only ingest-policy change from v1 is:

```text
max_table_block_chars = 12,000
```

No source file was modified. This removed route-sized table units while preserving the corpus and ground-truth task domain.

## Gate 1

```text
status                    PASS
source hash coverage      100%
ingest coverage           100%
semantic coverage         100%
blocks > 12,000 chars     0
blocks > model context    0
```

## Gate 2

```text
status          PASS
cases           132
needle kinds    11
modalities      text + table + image
blockers        none
```

Kind distribution remains:

```text
exact                15
semantic-paraphrase  15
exception            15
table-cell           15
image-text           12
contradiction        10
cross-file           10
date                 10
negative             10
number               10
supersession         10
```

Positive cases remain grounded to exact coverage units. Ground-truth target IDs and expected answers are scorer-side only.

## Why v2 supersedes v1

v1 correctly exposed a real flaw: a few table blocks were too large to participate cleanly in a strict 1× scale experiment.

v2 fixes the coverage-unit boundary rather than weakening the benchmark:

```text
v1 max table block        356,080 chars
v2 max table block         11,999 chars
source SHA set             unchanged
Gate 1 / Gate 2            still PASS
strict Gate 4 cross-file   BLOCKED → READY
```

## What remains unproven

```text
Gate 3  live multimodal fidelity        BLOCKED until an authorized provider credential is ready
Gate 4  frozen scale experiment         PREPARED, live curve not run
Gate 5  repeated-run drift              NOT RUN
```

Machine-readable evidence:

`benchmarks/results/nist-public-gate1-2-v2-2026-09-28.json`
