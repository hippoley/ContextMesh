# Draft intervention — Haystack #11867

Status: **ready, not posted**.

The current GitHub integration returned 403 when attempting to comment on `deepset-ai/haystack`. Do not describe this draft as posted.

Suggested comment:

One refinement that may keep `CONTEXT_LOSS` useful as the API grows: model it as a **stage transition**, not only a terminal failure class.

Two different failures can look identical if the diagnostic stops at retriever/reranker output:

```text
candidate discovered
  -> retrieved
  -> reranked
  -> selected
  -> rendered / model-visible
```

I recently measured both shapes against current open-source systems:

1. **eligibility loss** — a decisive source was present at rank 17 in two controlled corpora, but a visible top_k=5 made it unavailable downstream. The retriever had found it; the cutoff hid it.
   Repro/result: https://github.com/hippoley/ContextMesh/blob/main/docs/reality/Cognee-1.6.0-rank-depth-2026-09-24.md

2. **visibility loss after selection** — on current Dify main, an 11,343-byte instruction source was successfully selected/read, but the ordinary shell observation exposed only first 4 KiB + last 4 KiB. A decisive middle instruction was absent from model-visible context even though source-level “coverage” looked complete.
   Repro/result: https://github.com/hippoley/ContextMesh/blob/main/docs/reality/Dify-42889-2026-09-24.md

That suggests a compact diagnostic record could be more durable than adding many mutually exclusive enums:

```python
DocumentTransition(
    document_id=...,
    retrieved_rank=17,
    reranked_rank=17,
    selected=False,
    rendered=False,
    reason="top_k",
)

DocumentTransition(
    document_id=...,
    retrieved_rank=1,
    selected=True,
    rendered=True,
    source_bytes=11343,
    visible_bytes=8192,
    visible_ranges=[(0, 4096), (7247, 11343)],
    reason="transport_truncation",
)
```

Then higher-level classes such as `FILTER_EXCLUSION`, `SCORE_BELOW_CUTOFF`, `CONTEXT_LOSS`, or `EMPTY_CONTEXT` can be derived from the trace without losing the stage where evidence disappeared.

This also composes with `include_outputs_from`: diagnostics remain interpretive, but the unit of explanation becomes “what happened to this candidate across stages?” rather than only “what final failure label applies?”

If this direction fits the RFC scope, I can turn the two cases above into small Haystack-shaped regression fixtures rather than proposing a new execution path.
