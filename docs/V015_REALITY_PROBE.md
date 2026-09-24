# ContextMesh v0.15 — Reality Probe

v0.15 changes the development question from “what else can we build?” to:

> Can retrieval eligibility change the evidence available to an evaluator?

The probe is intentionally small. It is not a general RAG leaderboard and it is not a benchmark claiming that one memory system is globally better than another.

## Why these scenarios exist

The initial probe suite is derived from failure classes visible in public Cognee issues:

- Cognee #3706: top-k crowding from near-duplicate / templated chunks, including a reported relevant chunk falling to rank 17 or outside top-20.
- Cognee #4462: a non-empty collection can return top-k nearest chunks even when the query is unrelated to the corpus.
- Cognee #4296: completion-style recall can produce assertions not supported by retrieved evidence in some query forms.
- Cognee #4236 / #3805: structured-input loss and inconsistent ranking channels are examples of information becoming unavailable or unequally weighted before downstream reasoning.

The synthetic probe corpora do not copy user corpora from those issues. They recreate only the failure mechanism.

## Scenarios

1. rare-exception
   - many high-overlap general-policy passages;
   - one differently worded legal-hold exception changes the verdict.

2. later-contradiction
   - many old passages support the candidate answer;
   - one later bulletin reverses the rule.

3. near-duplicate-crowding
   - repeated structured telemetry consumes the obvious ranking slots;
   - one differently worded manual-stop record is decisive.

4. unsupported-query
   - the corpus is non-empty;
   - none of it supports the question.

## Backends

### lexical-topk

A deterministic lexical control used to validate the benchmark mechanism.

It is deliberately simple and must not be described as Cognee, vector search, or a production retriever.

### contextmesh-full-coverage

This path creates a real ContextMesh manifest and runs the actual ProgressiveEvaluator.

The same lexical ranking is supplied as the preferred order, but every required document remains eligible. The run fails if execution coverage does not reach 100%.

This isolates the core invariant:

    ranking = scheduling, not filtering

### cognee-chunks

Optional live integration.

Install:

    pip install -e '.[cognee]'

Then run:

    contextmesh reality-probe --backend cognee --backend contextmesh --top-k 5

The adapter uses Cognee's current Python API:

- remember(list[str], dataset_name=...)
- search(..., query_type=SearchType.CHUNKS, top_k=N)

Every short benchmark document contains a CM_DOC_ID marker so returned chunks can be mapped back to benchmark source IDs.

Cognee is intentionally not installed in the default ContextMesh CI matrix. A missing Cognee installation is an explicit integration error, not a skipped “pass”.

## Same-model verdict pass

Selection and reasoning are separate variables.

By default the probe computes an evidence-available verdict from benchmark ground truth. That tells us whether decisive evidence survived the backend's eligibility step.

To test actual model behavior with the same model after selection, configure a normal ContextMesh model route and run:

    contextmesh reality-probe \
      --backend lexical \
      --backend contextmesh \
      --route-id local-qwen \
      --format markdown

The same judge sees the evidence selected by each backend and returns:

- supports
- contradicts
- mixed
- unsupported

This lets the report distinguish:

1. evidence was not selected;
2. evidence was selected but the judge interpreted it incorrectly.

## Metrics

Each scenario/backend reports:

- selected documents;
- coverage;
- decisive evidence recall;
- first decisive rank;
- evidence-available verdict;
- expected verdict;
- exception preservation;
- contradiction preservation;
- source traceability;
- forced non-empty context on unsupported questions;
- latency;
- token/cost usage when a live model route is used.

## Commands

Default mechanism smoke:

    contextmesh reality-probe --format markdown

Increase crowding:

    contextmesh reality-probe --crowding 100 --top-k 5 --format markdown

Live Cognee CHUNKS:

    contextmesh reality-probe \
      --backend cognee \
      --backend contextmesh \
      --top-k 5 \
      --format markdown

Live model verdict over both selections:

    contextmesh reality-probe \
      --backend cognee \
      --backend contextmesh \
      --route-id <route-id> \
      --format markdown

## Honesty boundary

Passing the deterministic probe proves only that the benchmark can expose eligibility-induced blind spots and that ContextMesh preserves every required document under its own runtime invariant.

It does not prove that Cognee misses those documents.

A statement about Cognee is allowed only after the optional Cognee backend has been run against the current Cognee version and the resulting report has been saved with version/configuration details.

Likewise, a retrieval miss does not automatically imply a wrong LLM answer; the optional same-model verdict pass measures that second step separately.

## Stop / continue rule

The probe is intended to decide whether ContextMesh should keep existing.

Evidence for continuing:
- current retrieval systems repeatedly omit decisive evidence in realistic verification tasks;
- full-coverage execution restores materially different, correct verdicts at acceptable cost.

Evidence for stopping or narrowing further:
- current retrieval/memory systems reliably preserve decisive evidence across these scenarios;
- or full coverage adds cost without measurable verdict improvement.

That decision should be based on saved probe reports, not architecture preference.
