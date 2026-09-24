# Temporal Memory Reality Replay — Mem0 #5352

Source discussion:
https://github.com/mem0ai/mem0/issues/5352

This probe targets a different failure stage from retrieval cutoffs or transport truncation.

The evidence is still present. The question is:

> when several memories conflict, which one is still allowed to act as the current truth?

## Why this exists

The Mem0 #5352 thread contains repeated production reports that:

- vector similarity does not encode temporal authority;
- “newer” can be a transient error, stale echo, or temporary override;
- cosine-near facts can be semantic opposites;
- invalidation should be different from eviction;
- superseded/refuted history should remain auditable;
- retrieval-time gating must respect lifecycle state.

The benchmark turns those claims into deterministic replay cases.

## Cases

### transient-newer-is-not-truth

A verified production database port is followed by a newer, unverified transient observation.

Expected current truth: the older verified configuration.

### temporary-override-expired

A verified emergency region override is valid for six hours and is newer than the primary region.

The replay runs after the override has expired.

Expected current truth: the older primary-region policy.

### verified-preference-change

A real user preference change is explicitly verified and supersedes the older preference.

Expected current truth: the newer verified preference.

### refuted-latest-write

A newer assistant-echo memory is later marked refuted.

Expected current truth: the earlier verified monitoring fact.

## Policies

### last-write-wins

Newest non-closed memory wins.

This intentionally ignores verification and validity intervals. It is a baseline, not a recommended policy.

### destructive-newest-wins

Models a hygiene pass that compacts conflicting history down to the newest row.

It measures both answer correctness and whether audit history survives.

### verified-supersession

A reference policy derived from the discussion:

- explicit `superseded/refuted` lifecycle state;
- validity intervals;
- verified facts outrank unverified contested facts;
- closed/expired facts remain inspectable but not authoritative;
- no destructive deletion is required.

This is **not claimed to be current Mem0 behavior**. It is a falsifiable policy baseline.

## Run

```bash
contextmesh memory-replay --format markdown
```

## What a useful external result looks like

The important comparison is not “ContextMesh vs Mem0.”

It is:

```text
same conflicting memory history
        |
        +-- recency-only authority policy
        |
        +-- explicit verification + lifecycle + validity policy
```

If the reference policy does not improve correctness on controlled conflict cases, the added complexity is not justified.

If it does, the next step is to run the same histories through an actual memory implementation instead of treating the reference policy as evidence of upstream behavior.

## Honesty boundary

This benchmark is derived from failure modes discussed by Mem0 users, but it does not execute Mem0 itself.

Until a live Mem0 integration is added, results should be described as:

- issue-derived temporal-memory mechanism probes;
- not a Mem0 accuracy benchmark;
- not evidence that Mem0 currently implements last-write-wins;
- not evidence that the reference policy is sufficient for all memory conflicts.
