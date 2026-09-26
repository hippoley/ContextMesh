---
name: Reality failure
about: Bring a real context/retrieval/memory/provenance failure for reproduction
title: "[Reality] "
labels: ""
assignees: ""
---

## What looked healthy?

What did the system appear to do correctly? For example: retrieved results, loaded a file, returned a memory, passed a tool result, or produced a fluent answer.

## What actually failed?

What decisive evidence was missing, hidden, stale, conflicting, truncated, mis-scoped, or otherwise unable to participate?

## Public artifact

Link a public issue / PR / reproduction / log if one exists.

## Smallest reproduction

A synthetic fixture is preferred. Please do not upload private or sensitive corpora.

## Suspected failure stage

Pick any that seem relevant; uncertainty is fine.

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

What are you doing today to survive this failure?

## Ownership

- [ ] I only want to report the case.
- [ ] I can help reproduce it.
- [ ] I want to own this probe/backend.
- [ ] I can contribute a regression fixture or upstream patch.

A counterexample that disproves a ContextMesh claim is especially welcome.
