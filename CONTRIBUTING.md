# Contributing to ContextMesh

ContextMesh is built around one rule: **claims should survive contact with real systems**.

The project keeps three core invariants:

1. Retrieval may schedule reading order; it must not silently remove required coverage units.
2. A final score must stay locked until ingest, semantic-readiness, and execution gates pass.
3. Raw provenance must remain recoverable from every derived ContextBlock/evidence item.

## The best first contribution

You do not need to understand the whole runtime.

Start with one real failure artifact:

- a public upstream issue or PR;
- a minimal reproduction;
- a small synthetic corpus;
- a log showing where evidence disappeared;
- an ugly workaround you already use in production.

Post it in [Issue #1 — Bring one real context failure](https://github.com/hippoley/ContextMesh/issues/1).

We will help reduce it to the smallest deterministic probe that can prove or falsify the mechanism.

## Contribution lanes

### 1. Reality Probe owner

Adopt one backend or failure class and keep its probe current as upstream changes.

Current lanes are tracked in [Issue #2 — Contributor board](https://github.com/hippoley/ContextMesh/issues/2).

Good ownership targets include Cognee, Mem0, Dify, RAGFlow, Haystack, or a new system you already use.

### 2. Upstream reproduction / regression fixture

Trace the current upstream code, reproduce the behavior, and produce a fixture that the upstream project can adopt.

This is often more valuable than adding ContextMesh-specific code.

### 3. Backend adapter

Add a small integration that lets the same Reality Probe run against another retriever, memory store, agent runtime, or model transport.

Adapters should expose what evidence was actually available, not hide it behind a single score.

### 4. Evidence lifecycle instrumentation

Improve visibility across:

```text
ingested -> stored -> retrieved -> eligible -> rendered -> model-visible -> authority -> judged
```

Useful changes include rank/cutoff/drop reasons, byte/span visibility, authority state, provenance, and deterministic receipts.

### 5. Falsify ContextMesh

If a ContextMesh claim does not hold, open an issue or PR with the counterexample.

A good falsification is a first-class contribution.

## What makes a strong PR

Prefer changes containing at least two of:

1. a current-upstream reproduction;
2. a measured result;
3. a regression fixture or small implementation another project can adopt.

Avoid broad architecture work without a reality artifact.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,rich]'
pytest -q
contextmesh serve --host 127.0.0.1 --port 8765
```

For S3 / MinIO coverage:

```bash
pip install -e '.[dev,rich,s3]'
pytest -q tests/test_v14_minio_e2e.py
```

The public CI also exercises the MinIO multipart path.

## Working with upstream communities

Do not enter another repository with a product pitch.

A useful external intervention should contain at least two of:

- a reproduction that runs on current upstream;
- a measurement that changes the understanding of the failure;
- a small patch / contract / fixture upstream can adopt without adopting ContextMesh.

If the comment needs "check out my project" to be useful, it is not ready.

## Becoming a long-term maintainer

Repeated contribution is more important than permission ceremony.

If you keep a probe/backend current, review related PRs, reproduce upstream regressions, or maintain a failure taxonomy over time, claim that lane in the contributor board. We want contributors to become visible owners of parts of the project rather than one-off patch submitters.

Submit code changes with tests that exercise the affected coverage, fidelity, or evidence-lifecycle contract.
