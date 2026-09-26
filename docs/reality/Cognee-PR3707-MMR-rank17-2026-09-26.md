# Cognee MMR rank-depth reality result — 2026-09-26

Source run:
https://github.com/hippoley/ContextMesh/actions/runs/36213382612

This probe asks a narrow question:

> On the exact controlled corpora where released Cognee 1.6.0 `SearchType.CHUNKS` placed the decisive source at rank 17, does the MMR selector proposed in Cognee PR #3707 move that source into the visible top-5?

## What was compared

### Baseline

- Cognee 1.6.0
- live `SearchType.CHUNKS`
- GLiNER/local embedding path
- 16 distractors + 1 decisive source
- visible cutoff: top-5
- deep diagnostic fetch: 50

### Candidate

Cognee PR #3707 is still unmerged. Its exact head for this probe was:

`d1625f2a87e562da2ae95242f00b0a1866c2209b`

The PR's full branch is not currently a clean end-to-end comparison target against the released probe environment: its older `remember()` path no longer accepts the released `extractor` argument and, without that path, requires an LLM API key.

Rather than invent credentials or silently modify the upstream implementation, the benchmark:

1. runs released Cognee 1.6.0 live;
2. exports the actual deep CHUNKS candidate order and active Cognee embeddings;
3. checks out the exact PR #3707 source;
4. extracts and executes the PR's original `_cosine_similarity()` and `mmr_select()` functions;
5. applies that exact selector to the same candidate order and embeddings.

This isolates the question the MMR PR is intended to answer while keeping the integration limitation explicit.

## Result

| Scenario | Released CHUNKS decisive rank | PR #3707 MMR decisive rank | Released top-5 | MMR top-5 | Mean pairwise cosine: released → MMR | Contradiction available |
| --- | ---: | ---: | --- | --- | --- | --- |
| near-duplicate-crowding | **17** | **2** | omitted | included | **0.9961 → 0.8965** | no → **yes** |
| rare-exception | **17** | **2** | omitted | included | **0.9954 → 0.8635** | no → **yes** |

In both controlled scenarios, the MMR selector moved the decisive source from rank 17 to rank 2. The decisive source therefore entered the visible top-5, changing the available evidence from insufficient to contradiction-present.

The mean pairwise cosine among the selected top-5 also fell substantially:

- near-duplicate-crowding: about 0.9961 → 0.8965
- rare-exception: about 0.9954 → 0.8635

The maximum pairwise cosine changed much less, which is expected: MMR diversified the set without eliminating every highly similar pair.

## What this changes

The earlier Cognee Reality Probe established:

```text
CHUNKS rank 17
+ top_k=5 eligibility cutoff
= decisive evidence unavailable
```

This follow-up shows that, for these two fixtures, the proposed MMR algorithm can change the first part:

```text
MMR rank 2
+ top_k=5
= decisive evidence available
```

That is a useful boundary for ContextMesh.

The evidence does **not** support a claim that full coverage is categorically better than MMR. On these controlled cases, MMR addresses the observed crowding failure directly and cheaply.

The remaining distinction is structural:

```text
MMR:
improve ordering so important evidence is more likely to enter top-k

ContextMesh:
do not make rank determine final eligibility when complete coverage is required
```

They solve different layers and can be complementary.

## Limits

- These are controlled synthetic corpora, not a broad Cognee benchmark.
- The baseline is live Cognee 1.6.0; the MMR arm is the exact pure selector from unmerged PR #3707 replayed over the baseline candidate order and embeddings.
- This does not validate PR #3707's full integration path.
- `lambda_mult=0.5` was tested.
- No downstream live-LLM answer verdict was run.
- This result should not be generalized to arbitrary corpora, larger candidate pools, other embedding models, or other MMR parameters.

Machine-readable result:
`benchmarks/results/cognee-mmr-rank17-2026-09-26.json`

Runnable probes:

- `benchmarks/cognee_mmr_rank17_probe.py`
- `benchmarks/cognee_pr3707_mmr_replay.py`
