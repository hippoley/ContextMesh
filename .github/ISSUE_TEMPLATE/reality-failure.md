---
name: Reality failure
about: Bring a real retrieval, context, memory, provenance, or model-visibility failure
title: "[Reality] "
labels: ""
assignees: ""
---

> The best report is a failure that **looked healthy until one decisive piece of evidence stopped participating**. Synthetic/minimal fixtures are preferred; do not upload private data.

## One-sentence failure

<!-- Example: “The source is retrieved and read, but the decisive middle instruction is absent from the model-visible observation.” -->

## What looked healthy?

What did the system appear to do correctly?

Examples:

- retrieval returned results;
- a source/file was selected and read;
- a memory was returned;
- a graph traversal found plausible paths;
- a tool call succeeded;
- the final answer looked fluent.

## What actually failed?

What decisive evidence was missing, hidden, stale, conflicting, truncated, mis-scoped, pruned, or otherwise unable to participate?

## Pinned environment

Please pin as much as you can.

```text
project / package:
version:
commit SHA:
runtime:
model / embedder / reranker:
relevant config:
```

## Public artifact

Link the upstream issue, PR, benchmark, log, trace, or public reproduction if one exists.

## Smallest reproduction

A synthetic fixture is preferred.

```text
<input / corpus / graph / memory sequence>
```

Exact command, if available:

```bash
# reproduce here
```

## Observed vs expected

**Observed**

```text
<smallest useful measurement>
```

**Expected**

```text
<what would make the decisive evidence usable>
```

## Suspected evidence stage

Uncertainty is fine.

- [ ] ingested
- [ ] stored
- [ ] retrieved
- [ ] eligible
- [ ] rendered
- [ ] model-visible
- [ ] authority
- [ ] judged
- [ ] not sure

## Current workaround

What are you doing today to survive this failure? Manual re-read, larger top-k, prompt duplication, explicit lifecycle filters, retries, custom patch, etc.

## What would falsify this report?

What result would show that the suspected mechanism is wrong?

<!-- This is intentionally first-class. A probe that disproves the initial theory is still a successful Reality Delta. -->

## Ownership

- [ ] I only want to report the case.
- [ ] I can help reproduce it.
- [ ] I want to own this probe/backend.
- [ ] I can contribute a regression fixture or upstream patch.

A counterexample that disproves a ContextMesh claim is especially welcome.

---

Useful references:

- [Reality Probe Index](../../docs/reality/README.md)
- [Evidence Lifecycle](../../docs/EVIDENCE_LIFECYCLE.md)
- [Contributor Board](https://github.com/hippoley/ContextMesh/issues/2)
