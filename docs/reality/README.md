# ContextMesh Reality Probe Index

ContextMesh is a **reality-first context verification lab**. This directory contains pinned external reproductions, before/after fixes, falsification results, and upstream intervention notes.

The goal is not to rank frameworks. The goal is to answer a narrower question:

> **Where did decisive evidence stop participating — and can that boundary be reproduced?**

## Verified Reality Probes

| System | Failure stage | Result | Status | Date | Evidence |
| --- | --- | --- | --- | --- | --- |
| **ContextMesh self-contract** | over-context execution | **~1.10M estimated corpus tokens** executed through a **16K simulated model window** with 384/384 required blocks inspected and decisive exception preserved | validated synthetic execution contract | 2026-09-27 | [result](Over-Context-1.1M-2026-09-27.md) · [JSON](../../benchmarks/results/over-context-1.1m-2026-09-27.json) · [run](https://github.com/hippoley/ContextMesh/actions/runs/36299795477) |
| **ContextMesh NIST public proof v2** | corpus reality + benchmark ground truth | **12 real NIST/AIRC files · 3.88M est. tokens · 29.6212× 131,072-token context · 1,905 bounded coverage units · 132 frozen text/table/image cases** | **Gate 1 PASS · Gate 2 PASS · Gate 3 blocked · Gate 4 prepared · Gate 5 not run** | 2026-09-28 | [evidence](Big-Context-NIST-Gate1-2-v2-2026-09-28.md) · [JSON](../../benchmarks/results/nist-public-gate1-2-v2-2026-09-28.json) · [run](https://github.com/hippoley/ContextMesh/actions/runs/36393959366) |
| **ContextMesh NIST Gate 4 preflight v2** | scale-experiment integrity | **strict 12-case panel · cross-file + all local positions · 6 exact anchors · nested 1.005× / 2.008× / 5.008× / 10.040× / 20.001× projections · stable fingerprints** | **PREPARED · live Gate 4 not run** | 2026-09-28 | [evidence](Big-Context-NIST-Gate4-Preflight-v2-2026-09-28.md) · [JSON](../../benchmarks/results/nist-public-gate4-preflight-v2-2026-09-28.json) · [run](https://github.com/hippoley/ContextMesh/actions/runs/36393959366) |
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
  -> inspected
  -> authority
  -> reduced
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
