# RAGFlow D24 — verified before/after patch

**Date:** 2026-09-26  
**Upstream:** `infiniflow/ragflow`  
**Pinned current-main commit:** `313ca90f6abd7682fe8523e16fd67b3653a3fa84`  
**Reality status:** current-main failure reproduced; minimal patch passes targeted service tests

Source run:
https://github.com/hippoley/ContextMesh/actions/runs/36215686041

## The failure

RAGFlow's own OpenAI catalog describes `gpt-4o` with two different constraints:

- `context_length = 128000`
- `max_output = 16384`

The model solver already preserves both as separate fields:

```text
ModelTarget.ContextLength = 128000
ModelTarget.MaxTokens     = 16384
```

But current `chat_pipeline.go` only carries `target.MaxTokens` into its LLM config. That same value is then reused for:

- knowledge budgeting;
- `messageFitIn(...)`;
- completion capacity.

So the 128K context model is fitted as though its context window were 16,384 tokens.

The before-probe classified current main as:

```text
status = broken
context_length = 128000
max_output = 16384
effective fit budget before 95% = 16384
```

## Minimal contract

The patch keeps the two constraints separate all the way through the chat request:

```text
knowledge budget  <- context_length
input/message fit <- context_length
generation cap    <- max_output / max_tokens

completion limit =
min(
  requested_output,
  max_output,
  context_length - used_prompt_tokens
)
```

The patch exposes `target.ContextLength` as `cfg["context_length"]`, reads it into a separate `modelContextLength`, uses it for knowledge/message fitting, and retains `modelMaxTokens` as the output ceiling.

A new `clampChatConfigBudgets()` helper enforces both constraints. The previous `clampChatConfigMaxTokens()` remains as a compatibility wrapper for existing callers and tests.

## Before / after

| Contract | Current main | Patched |
| --- | --- | --- |
| solver carries context length | yes | yes |
| solver carries max output | yes | yes |
| pipeline exposes context length | **no** | **yes** |
| knowledge budget uses context length | **no** | **yes** |
| message fit uses context length | **no** | **yes** |
| output cap remains separate | **no** | **yes** |
| effective pre-95% fit budget | **16,384** | **128,000** |

The same source-level contract probe was used on both sides:

```text
before patch -> broken
apply patch
after patch  -> fixed
```

## Real Go validation

The patched checkout was formatted and compiled through RAGFlow's actual `internal/service` package with:

```bash
CGO_ENABLED=0 go test ./internal/service \
  -run 'TestContextMeshD24SeparatesContextAndOutputBudgets|TestClampChatConfigMaxTokens' \
  -count=1 -v
```

Result:

```text
PASS
ok  ragflow/internal/service  0.042s
```

The new D24 test covers:

1. large context + smaller output ceiling: requested 50,000 → capped at 16,384;
2. remaining context tighter than output ceiling: 8,000 tokens remain → cap at 8,000;
3. exhausted context → explicit error even if output capacity otherwise remains.

Existing clamp tests also passed.

### Why CGO was disabled

The first full-package attempt with CGO enabled never reached the D24 tests because RAGFlow's parser dependency chain requires the external `office_oxide.h` native header.

D24 itself is pure budget logic and does not depend on Office/PDF parsing. RAGFlow provides non-CGO parser stubs, and the targeted package test succeeds with `CGO_ENABLED=0`. This limitation is recorded rather than hidden.

## Relationship to #20140 / #20207

RAGFlow issue #20140 tracks three related semantics problems. PR #20207 explicitly addresses the first two and explicitly says D24 is not covered.

This patch therefore does not duplicate #20207's claimed scope. It addresses the remaining D24 boundary:

> the resolver already knows the context window, but the chat execution path binds the output ceiling where the input/context budget is required.

## Artifacts

- Machine-readable result: `benchmarks/results/ragflow-d24-before-after-2026-09-26.json`
- Upstream-ready patch: `benchmarks/upstream-patches/ragflow-d24-separate-context-output.patch`
- Deterministic patcher: `benchmarks/ragflow_d24_apply_patch.py`
- Before/after probe: `benchmarks/ragflow_d24_contract_probe.py`
- Workflow: `.github/workflows/reality-ragflow-d24-patch.yml`
- Actions run: https://github.com/hippoley/ContextMesh/actions/runs/36215686041

## Limits

This is not upstream acceptance and it is not a live provider request. It is a pinned current-main reproduction plus a source-contract proof and targeted RAGFlow Go package test.

The next Reality Delta must come from RAGFlow: correction of the contract, request for the patch/test, or upstream adoption.
