# Mem0 2.2.0 temporal-authority reality result — 2026-09-24

Source run:
https://github.com/hippoley/ContextMesh/actions/runs/35969812150

Upstream commit:
`47a69e1e72dc562b6fdd49a9ef892229afc7508a`

## Setup

This experiment deliberately removed LLM extraction from the equation:

- Mem0 OSS 2.2.0
- local Qdrant
- local FastEmbed `BAAI/bge-small-en-v1.5`
- `infer=False`
- no LLM call
- semantic search, `top_k=10`, threshold 0, no reranker

Two conflicting memories were stored for the same fact key:

| Fact | Lifecycle | Verified | Event time |
| --- | --- | --- | --- |
| database port = 5432 | active | yes | 2026-09-01 |
| database port = 6543 | contested / transient | no | 2026-09-23 |

## Observed behavior

Default search returned **both** memories:

| Memory | Score | Lifecycle |
| --- | ---: | --- |
| port = 5432 | 0.425263 | active / verified |
| port = 6543 | 0.418039 | contested / unverified |

The semantic scores are close. Similarity by itself does not encode which fact is authoritative.

When the same query used an explicit lifecycle filter:

```python
filters={"user_id": user_id, "status": "active"}
```

only the verified active 5432 memory remained.

## What this establishes

Mem0 did **not** destroy the conflicting history in this probe. That is an important positive result.

The boundary exposed by the experiment is different:

> memory retrieval can surface evidence, but semantic similarity does not determine epistemic authority.

For this controlled pair, authority became correct only after the caller expressed lifecycle policy explicitly.

This supports a narrower ContextMesh role:

```text
memory store / retriever
        |
        v
candidate memories
        |
        v
authority / verification eligibility
        |
        v
downstream reasoning
```

ContextMesh should not become another memory database. A useful integration boundary is an authority/verifier layer that can preserve history while deciding whether a fact is active, contested, expired, superseded, refuted, or requires review.

## What this does not establish

This is not a claim that Mem0 is incorrect.

- Explicit metadata filtering is already supported and worked correctly.
- Only one live conflict pair was tested.
- No Mem0 LLM inference/merge behavior was tested.
- No reranker was used.
- A production policy may intentionally return multiple conflicting memories.

The result is evidence that **recency/similarity and truth authority are different dimensions**, which is also the core concern raised by the public discussion in Mem0 #5352.

Machine-readable snapshot:
`benchmarks/results/mem0-2.2.0-temporal-authority-2026-09-24.json`
