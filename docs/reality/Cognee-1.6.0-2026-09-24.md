# Reality result: Cognee 1.6.0 CHUNKS — 2026-09-24

This is the first saved external comparison produced by ContextMesh v0.15.

Source workflow:
https://github.com/hippoley/ContextMesh/actions/runs/35947688454

## Configuration

- ContextMesh: 0.15.0
- Cognee: 1.6.0
- Python: 3.12.14
- Cognee search path: SearchType.CHUNKS
- Cognee extraction: GLiNER
- local embedding path: Cognee default / fastembed
- top_k: 5
- crowding: 16
- live LLM verdict: not run

Each targeted scenario had 17 source documents: 16 high-overlap or near-duplicate distractors and one decisive exception/contradiction.

## Observed result

| Scenario | Backend | Coverage | Decisive evidence recall | Evidence-available verdict | Expected |
| --- | --- | ---: | ---: | --- | --- |
| rare-exception | ContextMesh full coverage | 100% | 100% | contradicts | contradicts |
| rare-exception | Cognee CHUNKS | 29% | 0% | unsupported | contradicts |
| near-duplicate-crowding | ContextMesh full coverage | 100% | 100% | contradicts | contradicts |
| near-duplicate-crowding | Cognee CHUNKS | 29% | 0% | unsupported | contradicts |

The Cognee workflow itself completed successfully. This was not an installation or adapter failure: Cognee remembered the corpus, CHUNKS returned results, and source markers mapped the returned chunks back to probe source IDs.

For both targeted scenarios, the decisive source was absent from Cognee's returned top five. ContextMesh used ranking only as execution order and still visited every required source.

## What this does establish

For these two controlled corpora, a current real memory/retrieval system can return plausible top-k context while omitting the one source that changes the evidence-available verdict.

That is the specific mechanism ContextMesh is designed to guard against.

## What this does not establish

This is not evidence that Cognee is globally worse than ContextMesh, or that Cognee memory is unsuitable for agents.

In particular:

- only SearchType.CHUNKS was tested;
- Graph Completion, Hybrid, MMR, truth weighting and other Cognee modes were not tested;
- the corpora are synthetic mechanism probes;
- no same-model downstream verdict was run;
- top-k retrieval and full-coverage verification solve different product problems.

The next stronger test is to give the selected evidence from each backend to the same model and measure whether the retrieval omission actually changes the final verdict.

The machine-readable snapshot is in:
benchmarks/results/cognee-1.6.0-2026-09-24.json
