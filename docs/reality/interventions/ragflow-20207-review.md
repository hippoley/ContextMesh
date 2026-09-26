# Draft upstream review — RAGFlow PR #20207

Independent check against PR head `7ce7c7e7375062eae15f33dd471788b9189a48fd` found one remaining service-layer semantics leak that looks in-scope for this PR.

`internal/service/model_service.go::modelInfoWithTenantExtra()` still does:

```go
model.MaxOutput = extra.MaxTokens
model.MaxTokens = extra.MaxTokens
```

and `ModelSolver.ResolveModelConfig()` still runs `maxTokensFromTenantModelExtra(...)` before returning `ModelTarget.MaxTokens`.

So a controlled case with catalog `MaxOutput=16384` plus tenant `extra.max_tokens=32000` still makes the service path treat the context-window override as a generation-output limit. That seems to violate this PR's intended invariant that tenant `max_tokens` has one meaning: context window.

Independent PR-head check:

https://github.com/hippoley/ContextMesh/actions/runs/36209224821

Output:

```text
CONFIRMED_20207_REVIEW_GAP tenant_extra.max_tokens=context_override remaining_service_effect=ModelInfo.MaxOutput+ModelTarget.MaxTokens
```

I would keep D24 (chat_pipeline using catalog MaxOutput as its message-fit/context budget) separate as already noted; this finding is only about the remaining `modelInfoWithTenantExtra` / `ModelSolver` path that appears to belong to #20140's first semantics item.
