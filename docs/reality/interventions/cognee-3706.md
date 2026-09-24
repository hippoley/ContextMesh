# Draft intervention — Cognee #3706

Status: **ready, not posted**.

The current GitHub integration returned 403 when attempting to comment on `topoteretes/cognee`. Do not describe this draft as posted.

Suggested comment:

I re-ran the crowding mechanism against **Cognee 1.6.0** itself and can confirm the “relevant item falls well outside visible top-k” case is still reproducible on the current `SearchType.CHUNKS` path.

Configuration:

- Cognee 1.6.0
- local GLiNER + fastembed path
- `SearchType.CHUNKS`
- visible `top_k=5`
- deeper diagnostic fetch `k=50`
- two controlled corpora, each with 16 high-overlap / near-duplicate distractors + 1 decisive exception

Observed in both corpora:

```text
decisive source rank = 17
visible top-5 decisive recall = 0%
```

I also ran the same ranking as a scheduling order without using top-k as an eligibility cutoff; the decisive source was still rank 17, but remained available later. So the comparison is not “a better retriever ranked it higher” — the useful distinction is exactly whether rank 17 is still allowed to participate downstream.

Saved run / machine-readable result:
https://github.com/hippoley/ContextMesh/blob/main/docs/reality/Cognee-1.6.0-rank-depth-2026-09-24.md

This does **not** establish that MMR is always the right fix. It does add a current-version regression case for the failure mode this RFC targets: structured/templated density can consume the visible slots while a semantically decisive but differently worded source sits much deeper in the same ranking.

One test shape I think would be useful for any `CHUNKS_MMR` implementation is therefore not just diversity@k, but:

`decisive-source rank / recall before vs after MMR`

on a corpus where the decisive source is intentionally outside the pure-similarity top-k. That catches the user-facing failure rather than only proving pairwise diversity increased.
