# ContextMesh Reality Probe Index

ContextMesh is a **reality-first context verification lab**. This directory contains pinned external reproductions, before/after fixes, falsification results, and upstream intervention notes.

The goal is not to rank frameworks. The goal is to answer a narrower question:

> **Where did decisive evidence stop participating — and can that boundary be reproduced?**

## Verified Reality Probes

| System | Failure stage | Result | Status | Date | Evidence |
| --- | --- | --- | --- | --- | --- |
| **Cognee 1.6.0** | `eligible` / rank cutoff | decisive source at **rank 17**, outside top-5 in two controlled CHUNKS fixtures | reproduced | 2026-09-24 | [rank-depth result](Cognee-1.6.0-rank-depth-2026-09-24.md) · [JSON](../../benchmarks/results/cognee-1.6.0-rank-depth-2026-09-24.json) |
| **Cognee PR #3707** | `eligible` / diversification | exact MMR selector moved decisive source **17 → 2** in both fixtures | **falsification / positive upstream result** | 2026-09-26 | [before/after](Cognee-PR3707-MMR-rank17-2026-09-26.md) · [JSON](../../benchmarks/results/cognee-mmr-rank17-2026-09-26.json) · [run](https://github.com/hippoley/ContextMesh/actions/runs/36213382612) |
| **RAGFlow current main** | context-budget semantics | `128000` context was effectively fitted as `16384` because max output was reused as input budget | reproduced | 2026-09-26 | [D24 proof](RAGFlow-D24-2026-09-26.md) · [JSON](../../benchmarks/results/ragflow-d24-2026-09-26.json) |
| **RAGFlow D24 patch** | context-budget semantics | split `context_length` from `max_output`; targeted `internal/service` Go tests pass | **validated patch** | 2026-09-26 | [before/after](RAGFlow-D24-before-after-2026-09-26.md) · [patch](../../benchmarks/upstream-patches/ragflow-d24-separate-context-output.patch) · [run](https://github.com/hippoley/ContextMesh/actions/runs/36215686041) |
| **Dify current main** | `rendered → model-visible` | source selected/read, but decisive middle span removed by ordinary shell rendering | reproduced | 2026-09-24 | [reproduction](Dify-42889-2026-09-24.md) · [JSON](../../benchmarks/results/dify-42889-2026-09-24.json) · [run](https://github.com/hippoley/ContextMesh/actions/runs/35966935382) |
| **Mem0 2.2.0** | `authority` | active verified and contested unverified memories both semantically retrievable; lifecycle filter resolves authority explicitly | reproduced boundary | 2026-09-24 | [authority replay](Mem0-2.2.0-temporal-authority-2026-09-24.md) · [JSON](../../benchmarks/results/mem0-2.2.0-temporal-authority-2026-09-24.json) · [run](https://github.com/hippoley/ContextMesh/actions/runs/35969812150) |

## Evidence lifecycle

Reality Probes classify the first meaningful failure boundary:

```text
ingested
  -> stored
  -> retrieved
  -> eligible
  -> rendered
  -> model-visible
  -> authority
  -> judged
```

This matters because very different failures can otherwise collapse into one vague statement such as “the context was missing.”

See [Evidence Lifecycle](../EVIDENCE_LIFECYCLE.md).

## Reality status vocabulary

**Reproduced**  
The failure mechanism was executed against a pinned external version or commit.

**Validated patch**  
The same failure contract changes from broken to fixed after a minimal patch, with executable tests.

**Falsification result**  
A later experiment weakens or invalidates an earlier ContextMesh-shaped claim. These are first-class successes.

**Boundary result**  
The upstream system preserves enough information for the caller to express the policy explicitly; the probe identifies where framework responsibility ends and caller policy begins.

**Upstream accepted**  
Reserved for a maintainer-reviewed or merged result. ContextMesh does not use this label for its own patches before upstream review.

## Public Reality Lab

The interactive surface is generated from the machine-readable result artifacts above.

Expected Pages URL after repository Pages enablement:

```text
https://hippoley.github.io/ContextMesh/
```

The published `reality-data.json` includes SHA-256 provenance for each source result file, so the public metrics can be traced to exact repository artifacts.

## External intervention rule

ContextMesh should enter another project's issue or PR with at least two of:

1. a current-upstream reproduction;
2. a measurement that changes understanding of the failure;
3. a small adoptable regression fixture, patch, or interface contract.

No product pitch is required.

See [External Demand Radar](EXTERNAL_DEMAND_RADAR.md) and the live [Contributor Board](https://github.com/hippoley/ContextMesh/issues/2).

## Bring a failure

The best next contribution is not another framework feature. It is a failure that still looks like success:

- the relevant source was retrieved but became ineligible;
- the file was read but the decisive span was not model-visible;
- a newer memory outranked authoritative state;
- a context budget was bound to the wrong model constraint;
- a graph traversal pruned the only path to a decisive exception.

Start with [Issue #1 — Bring one real context failure](https://github.com/hippoley/ContextMesh/issues/1).
