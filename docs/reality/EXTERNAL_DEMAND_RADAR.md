# External Demand Radar — 2026-09-26

This is not a list of repositories to advertise in. It is a list of **external pain artifacts where ContextMesh already has a relevant capability, benchmark, or implementation lesson**.

The rule is simple:

> Do not enter an external thread with a product claim. Enter with a reproduction, measurement, compatibility patch, or contract that makes the upstream project better.

## Current high-signal projects

| Project | Stars (snapshot) | Why it matters |
| --- | ---: | --- |
| RAGFlow | ~91.2k | retrieval, chunking, context-window and evaluation failures are actively discussed |
| Mem0 | ~65.9k | memory conflict, temporal hygiene and retrieval truth are live production problems |
| LlamaIndex | ~52.3k | strong context/memory ecosystem, but many obvious issues are already crowded with PRs |
| LightRAG | ~39.8k | context isolation and workspace correctness matter, but the most relevant issue is already crowded |
| Graphiti | ~31.1k | explicit graph-memory correctness and ingestion verification discussions |
| Haystack | active | retrieval diagnostics RFC maps directly to evidence-lifecycle tracing |

Repository-size/activity snapshot above is from 2026-09-24. External-contact and collision state below was refreshed on 2026-09-26.

## A — enter now

### Graphiti #1880 — ingestion-time verification hook

https://github.com/getzep/graphiti/issues/1880

**Why this is the cleanest ContextMesh-shaped opening**

The RFC asks for a hook between extracted/resolved graph facts and persistence. It explicitly wants enough context to verify faithfulness against the raw source.

That is a better integration point than trying to make ContextMesh another memory database.

A useful hook contract would separate:

- source faithfulness: does the resolved fact actually follow from the raw episode?
- store conflict: does it duplicate, contradict, or supersede persisted state?
- evidence/provenance: what source span and prior facts support the decision?
- outcome: accept / refuse / contested / require-review
- receipt: deterministic reason + verifier/version + evidence IDs

There is currently no linked PR.

**Reality status:** public ContextMesh comment posted. It points to the actual single/bulk pre-persistence seams on current Graphiti main and proposes a typed verification receipt rather than a product integration pitch.

**Intervention shape:** wait for maintainer feedback before adding more surface area.

### RAGFlow D24 — chat pipeline binds generation output as context budget

Provenance: the D24 note in https://github.com/infiniflow/ragflow/issues/20140. No standalone D24 issue was found at refresh time.

RAGFlow's own OpenAI catalog defines `gpt-4o` with `context_length=128000` and `max_output=16384`. On current main commit `313ca90f6abd7682fe8523e16fd67b3653a3fa84`, the resolver carries both `ModelTarget.ContextLength` and `ModelTarget.MaxTokens`, but `chat_pipeline` passes `target.MaxTokens` into its internal `max_tokens` config and then uses that value for `messageFitIn(..., modelMaxTokens*0.95)`.

**Reality status:** confirmed current-main code-path failure. The executable probe emitted:

```text
CONFIRMED_D24 catalog_context=128000 catalog_max_output=16384 chat_fit_source=target.MaxTokens effective_fit_budget=16384
```

Evidence:
- `benchmarks/results/ragflow-d24-2026-09-26.json`
- `docs/reality/RAGFlow-D24-2026-09-26.md`
- Actions run 36209134470

**Intervention shape:** this is now a focused upstream issue/patch candidate, but the fix must keep context-window fitting and generation-output limiting as two separate constraints. Do not "fix" it by globally replacing one with the other.

### RAGFlow #20141 — Go/Python truncation parity

https://github.com/infiniflow/ragflow/issues/20141

The same media-adjacent context can become a different stored body and chunk ID depending on whether Go or Python performed the truncation.

This is source-fidelity debt, not cosmetic chunking behavior.

No PR was found for the issue.

**Intervention shape:** a shared boundary fixture plus the smallest parity fix. Do not bundle all related parser-config follow-ups unless maintainers ask.

### Dify #42889 — selected source, hidden middle span

https://github.com/langgenius/dify/issues/42889

Agent V2 can successfully pull a Skill and still expose only the first/last 4 KiB of a large `SKILL.md` when the model reads it through ordinary `shell_run`.

Current-main nuance matters:

- prompt-mentioned skills use `DifyConfigLayer._run_mentioned_pull()` → `run_remote_script()`, whose complete-output path is bounded at 1 MiB and carries the full `skill_md`;
- ordinary agent-driven `shell_run -> dify-agent config skills pull / cat SKILL.md` uses `render_prompt_observation_from_result()`, which applies the fixed 4 KiB head + 4 KiB tail model-visible budget.

So this is not “the source failed to load.” It is a path-dependent semantic visibility bug: the same source can be complete or incomplete depending on how the agent reaches it.

ContextMesh now has a matching `middle-instruction-truncation` Reality Probe and distinguishes:

- source not selected;
- source selected but decisive span hidden;
- source selected and semantically complete.

**Intervention shape:** propose a bounded/paginated full-read contract for instruction sources (or an explicit skill-read tool), plus a regression fixture with the decisive instruction placed in the hidden middle. Avoid simply raising the global shell-output constant.

No PR or assignee was found at scan time.

**Reality status:** current-main code-path probe succeeded. A synthetic 11,343-byte `SKILL.md` with a decisive middle instruction lost that instruction under the 8 KiB shell-rendering path, while the eager-pull complete-output path exposes a 1 MiB budget. A public evidence comment was posted to #42889.

Evidence:
- `benchmarks/results/dify-42889-2026-09-24.json`
- `docs/reality/Dify-42889-2026-09-24.md`
- Actions run 35966935382

## B — enter with evidence, not code competition

### RAGFlow #20140 / PR #20207 — occupied; review, do not compete

https://github.com/infiniflow/ragflow/pull/20207

PR #20207 now owns the direct implementation path for #20140. Its sole-active-instance fix covers the same 32K-vs-128K regression ContextMesh independently reproduced, so opening a competing PR would now be noise.

An independent review of PR head `7ce7c7e7375062eae15f33dd471788b9189a48fd` found one remaining in-scope semantics leak: `modelInfoWithTenantExtra()` still assigns tenant `extra.max_tokens` to both `ModelInfo.MaxOutput` and `ModelInfo.MaxTokens`, and `ModelSolver` still propagates the tenant value into `ModelTarget.MaxTokens`.

**Reality status:** review gap confirmed on the PR head. Upstream comment was attempted but the current GitHub integration returned 403, so the comment is **not posted**.

Evidence:
- `benchmarks/results/ragflow-pr-20207-review-2026-09-26.json`
- `docs/reality/RAGFlow-20207-review-2026-09-26.md`
- `docs/reality/interventions/ragflow-20207-review.md`
- Actions run 36209224821

**Intervention shape:** post the review invariant when upstream write access exists; do not fork/duplicate #20207.

### RAGFlow #20148 — why was this chunk dropped?

https://github.com/infiniflow/ragflow/issues/20148

There is already PR #20147, so opening a competing PR would be noise.

But the request itself is highly relevant: users can see returned scores but cannot see the candidates lost to threshold/cutoff or why.

Our live Cognee reality run gives a concrete reason this matters:

- the decisive source ranked 17 in two controlled scenarios;
- top-5 made it unavailable;
- full coverage preserved it without pretending retrieval ranked it better.

ContextMesh now records a source-level **eligibility trace**:

- source id
- rank
- selected or excluded
- manifest-required status
- decisive role
- decision
- exclusion/eligibility reason

**Intervention shape:** share the measurement and suggest that RAGFlow's debug funnel include rank/cutoff/drop reason per candidate. No marketing language.

### Mem0 #5352 — recency is not truth

https://github.com/mem0ai/mem0/issues/5352

This is an unusually valuable discussion because users have production workarounds and measured memory pollution.

The unresolved problem is not merely CRUD. It is epistemic:

- newer facts can be transient and wrong;
- semantically similar statements can be opposites;
- invalidation and eviction are different operations;
- retrieval gating decides which historical facts remain authoritative.

**Reality contact now implemented:** ContextMesh includes a deterministic temporal-conflict replay covering transient newer facts, expired overrides, verified preference changes, and refuted latest writes. It compares recency-only authority with an explicit verified/supersession-aware reference policy.

Run: `contextmesh memory-replay --format markdown`.

See [MEM0_TEMPORAL_MEMORY_REPLAY.md](MEM0_TEMPORAL_MEMORY_REPLAY.md).

**Intervention shape:** wait for CI-backed replay results, then contribute the measured policy failure rather than another architecture opinion. A live Mem0 integration should be the next gate before making any claim about Mem0 itself.

### Haystack #11867 — retrieval diagnostics should preserve the loss stage

https://github.com/deepset-ai/haystack/issues/11867

The RFC already distinguishes empty retrieval, filter exclusion, score cutoff and reranker context loss. External reality probes add a second axis: evidence can survive selection but disappear at rendering/model-visible transport.

Two measured examples now support a stage-transition model:

- Cognee: decisive source ranked 17, then lost at top-k eligibility.
- Dify: decisive source selected/read, then lost at model-visible rendering.

ContextMesh now represents this as:

`ingested → stored → retrieved → eligible → rendered → model-visible → judged`

with source-level failure classes and visible byte ranges.

**Reality status:** evidence-backed comment prepared in `docs/reality/interventions/haystack-11867.md`, but posting through the current GitHub integration returned 403.

**Intervention shape:** when write access exists, contribute stage-transition fixtures rather than another observability product pitch.

## C — do not pile on

These issues are relevant but already have active contributors or multiple PRs:

- LlamaIndex #23090 — priority truncation
- LlamaIndex #21950 — token accounting
- Mem0 #7302 — cancelled recall marks undelivered memory as seen
- LightRAG #2904 — workspace context leakage
- RAGFlow #16362 — silent 8K truncation
- Graphiti #1728 — unrelated edge invalidation
- CrewAI #7616 — silent knowledge chunk loss; PR #7617 already active
- CrewAI #7013 — provider truncation detection; multiple PRs already active
- CrewAI #7303 — model context windows; multiple PRs already active
- LangChain #36745 — embedding count mismatch; multiple PRs already active

The useful lesson is to absorb their failure mechanisms into our probes, not compete for the same patch.

## Visibility strategy

The goal is not comment volume.

A good external intervention should contain at least two of these three:

1. a minimal reproduction that runs on current upstream;
2. a measured result that changes the understanding of the bug;
3. a small patch or interface proposal that upstream can adopt without adopting ContextMesh.

If an intervention needs the phrase “check out my project” to be useful, it is not ready.


## Current external-contact status

| Target | State | Reality delta |
| --- | --- | --- |
| Graphiti #1880 | **public comment posted** | exact verifier hook boundary + receipt contract |
| Dify #42889 | **public comment posted** | selected/read source can lose decisive middle span |
| RAGFlow D24 | **verified current-main code path** | 128K context model is fitted against 16,384 MaxOutput budget |
| RAGFlow #20140 / PR #20207 | **existing PR; review evidence ready, write blocked** | remaining service path still leaks context override into generation MaxOutput |
| RAGFlow #20148 | **draft ready; upstream write blocked** | rank/cutoff/drop-reason diagnostic proposal |
| Cognee #3706 | **draft ready; upstream write blocked** | Cognee 1.6.0 decisive source rank 17 in two probes |
| Haystack #11867 | **draft ready; upstream write blocked** | retrieval diagnostics extended through model-visible stage |

The target is not maximum comment count. A useful Reality Delta is a maintainer reply, accepted test fixture, patch review, merged change, or upstream adoption of the diagnostic contract.
