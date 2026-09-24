# Rank-depth reality result — Cognee 1.6.0

Source run:
https://github.com/hippoley/ContextMesh/actions/runs/35948269281

This follow-up separates **ranking quality** from **eligibility policy**.

Configuration:

- Cognee 1.6.0
- SearchType.CHUNKS
- GLiNER + Cognee local default/fastembed path
- decision top-k: 5
- deeper rank fetch: 50
- 16 distractors + 1 decisive source per scenario
- no live LLM verdict

## Result

| Scenario | Decisive rank | Cognee visible top-5 | ContextMesh eligibility |
| --- | ---: | --- | --- |
| rare-exception | **17** | omitted | preserved |
| near-duplicate-crowding | **17** | omitted | preserved |

The important point is that **ContextMesh did not rank the decisive source better**. Its scheduling order also placed the decisive source at rank 17.

The difference was:

```text
same late-ranked evidence
        |
        +-- top-k eligibility -> rank 17 is absent from evidence
        |
        +-- full-coverage eligibility -> rank 17 is read later, but still participates
```

For both controlled scenarios:

- Cognee top-5 decisive recall: 0%
- ContextMesh decisive recall: 100%
- Cognee evidence available at cutoff: insufficient to detect the contradiction
- ContextMesh evidence available after coverage: contradiction present

This is a stronger test of the ContextMesh invariant than a simple “our retrieval found a better result” comparison, because retrieval quality is not the claimed advantage.

## Limits

This remains a controlled mechanism test, not a general benchmark of Cognee.

Only Cognee CHUNKS is tested. Cognee can use other modes, larger top-k values, graph completion, hybrid retrieval, future relevance thresholds, MMR, and other techniques.

The result also does not yet show that a downstream LLM changes its final answer. That requires the same-model verdict pass over each backend's selected evidence.

Machine-readable result:
`benchmarks/results/cognee-1.6.0-rank-depth-2026-09-24.json`
