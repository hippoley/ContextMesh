# Over-context execution contract — 12 files / ~1.1M estimated tokens

**Date:** 2026-09-27  
**Run:** https://github.com/hippoley/ContextMesh/actions/runs/36299795477

## Question

Can ContextMesh execute a corpus that is much larger than the model-facing context budget **without pretending that the model saw the whole corpus in one prompt**?

This is an execution-contract test, not a long-context model benchmark.

## Fixture

The benchmark generates:

- **12 synthetic text files**
- **4,400,939 characters**
- approximately **1,100,234 tokens** using a fixed 4 chars/token estimate
- a simulated model-facing context budget of **16,000 tokens**
- one decisive exception hidden around the middle of file 11

The corpus is therefore approximately **68.765× larger** than the simulated per-request model window.

The decisive marker is:

```text
DECISIVE_EXCEPTION_17_4
```

The evaluator receives only one preferred block in its requested order. ContextMesh may use that preference for scheduling, but the full-coverage contract must still make every required block eligible for inspection.

## Result

```text
required blocks              384
visited blocks               384
coverage                     1.0
judge calls                  384

max observed request chars   12,652
max permitted request chars  64,000
request budget respected     true

execution contract           full-coverage
transition receipts          384
transition chain valid       true

decisive exception survived  true
DecisionBundle exceptions    3
complete                     true
```

## What this proves

For this synthetic fixture, ContextMesh can execute a corpus whose estimated token volume is far larger than the model-facing request budget while preserving the following contract:

```text
large external corpus
        ↓
bounded block reads
        ↓
100% required-block inspection
        ↓
typed evidence
        ↓
DecisionBundle
        ↓
final judgment
```

The runtime did **not** place ~1.1M estimated tokens into a single model request.

The largest measured synthetic request was only 12,652 characters against a configured 64,000-character budget.

## What this does not prove

This result does **not** mean:

- ContextMesh gives a model a native 1.1M-token attention window;
- a real LLM will recover every semantic fact with 100% recall;
- the 4 chars/token approximation equals any provider's exact tokenizer;
- the current synthetic BudgetJudge measures reasoning quality;
- latency/cost at 1.1M tokens with a paid external model has been benchmarked here.

It validates **execution shape, coverage accounting, bounded requests, transition receipts, and decisive-evidence preservation**.

The next stronger test is the same contract with a real model route and exact provider tokenizer/cost telemetry.

## Reproduce

```bash
python benchmarks/over_context_execution.py \
  --target-tokens 1100000 \
  --files 12 \
  --simulated-context-tokens 16000
```

Source:

- [benchmark](../../benchmarks/over_context_execution.py)
- [machine-readable result](../../benchmarks/results/over-context-1.1m-2026-09-27.json)
