from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_chat_pipeline(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    # Surface the already-resolved context window on both model-resolution branches.
    marker_default = '''\t\tcfg["model_type"] = s.resolveChatModelType(ctx, chat.TenantID, modelTargetRef(target))
\t\tcfg["is_tools"] = target.SupportsTools
'''
    replacement_default = '''\t\tcfg["context_length"] = target.ContextLength
\t\tcfg["model_type"] = s.resolveChatModelType(ctx, chat.TenantID, modelTargetRef(target))
\t\tcfg["is_tools"] = target.SupportsTools
'''
    text = replace_once(text, marker_default, replacement_default, "default context_length exposure")

    marker_explicit = '''\tcfg["model_type"] = s.resolveChatModelType(ctx, chat.TenantID, chat.LLMID)
\tcfg["is_tools"] = target.SupportsTools
'''
    replacement_explicit = '''\tcfg["context_length"] = target.ContextLength
\tcfg["model_type"] = s.resolveChatModelType(ctx, chat.TenantID, chat.LLMID)
\tcfg["is_tools"] = target.SupportsTools
'''
    text = replace_once(text, marker_explicit, replacement_explicit, "explicit context_length exposure")

    phase2 = '''\t\tmodelMaxTokens := 8192
\t\tif llmModelConfig != nil {
\t\t\t// Treat max_tokens=0 as unset (default 8192) — mirrors
\t\t\t// PR #16413 Python fix: model_extra.get("max_tokens") or 8192
\t\t\tif mt, ok := llmModelConfig["max_tokens"].(int); ok && mt > 0 {
\t\t\t\tmodelMaxTokens = mt
\t\t\t}
\t\t}
'''
    phase2_fixed = '''\t\tmodelMaxTokens := 8192
\t\tmodelContextLength := 8192
\t\tif llmModelConfig != nil {
\t\t\t// max_tokens is the generation/output cap. Context fitting must use
\t\t\t// the separately resolved context_length.
\t\t\tif mt, ok := llmModelConfig["max_tokens"].(int); ok && mt > 0 {
\t\t\t\tmodelMaxTokens = mt
\t\t\t}
\t\t\tif cl, ok := llmModelConfig["context_length"].(int); ok && cl > 0 {
\t\t\t\tmodelContextLength = cl
\t\t\t}
\t\t}
'''
    text = replace_once(text, phase2, phase2_fixed, "runtime budget split")

    text = replace_once(
        text,
        "\t\tknowledges = s.kbPrompt(kbinfos, modelMaxTokens)\n",
        "\t\tknowledges = s.kbPrompt(kbinfos, modelContextLength)\n",
        "knowledge budget",
    )

    text = replace_once(
        text,
        "s.messageFitIn(llmMessages, int(float64(modelMaxTokens)*0.95))",
        "s.messageFitIn(llmMessages, int(float64(modelContextLength)*0.95))",
        "message fit budget",
    )

    text = replace_once(
        text,
        '''\t\tcommon.Debug("Messages fitted in token budget",
\t\t\tzap.Int("model max_tokens", modelMaxTokens),
\t\t\tzap.Int("used_token_count", usedTokenCount),
''',
        '''\t\tcommon.Debug("Messages fitted in token budget",
\t\t\tzap.Int("model context_length", modelContextLength),
\t\t\tzap.Int("model max_output", modelMaxTokens),
\t\t\tzap.Int("used_token_count", usedTokenCount),
''',
        "budget diagnostics",
    )

    text = replace_once(
        text,
        "clampChatConfigMaxTokens(chatCfg, modelMaxTokens, usedTokenCount+citationTokens)",
        "clampChatConfigBudgets(chatCfg, modelContextLength, modelMaxTokens, usedTokenCount+citationTokens)",
        "completion clamp call",
    )

    old_helper = '''func clampChatConfigMaxTokens(cfg *modelModule.ChatConfig, modelMaxTokens, usedTokenCount int) (int, bool, error) {
\tif usedTokenCount >= modelMaxTokens {
\t\treturn 0, false, fmt.Errorf("prompt uses %d tokens, leaving no completion capacity for model max_tokens %d", usedTokenCount, modelMaxTokens)
\t}
\tif cfg == nil || cfg.MaxTokens == nil {
\t\treturn 0, false, nil
\t}
\tadjusted := *cfg.MaxTokens
\tif adjusted <= 0 {
\t\tcfg.MaxTokens = nil
\t\treturn 0, false, nil
\t}
\tremainingTokens := modelMaxTokens - usedTokenCount
\tif adjusted > remainingTokens {
\t\tadjusted = remainingTokens
\t}
\tcfg.MaxTokens = &adjusted
\treturn adjusted, true, nil
}
'''
    new_helper = '''// clampChatConfigBudgets keeps the provider's generation cap separate from the
// model context window. A completion must fit both constraints: it cannot exceed
// maxOutput, and prompt+completion cannot exceed contextLength.
func clampChatConfigBudgets(cfg *modelModule.ChatConfig, contextLength, maxOutput, usedTokenCount int) (int, bool, error) {
\tif contextLength <= 0 {
\t\tcontextLength = maxOutput
\t}
\tif maxOutput <= 0 {
\t\tmaxOutput = contextLength
\t}
\tif usedTokenCount >= contextLength {
\t\treturn 0, false, fmt.Errorf("prompt uses %d tokens, leaving no completion capacity for model context_length %d", usedTokenCount, contextLength)
\t}
\tif cfg == nil || cfg.MaxTokens == nil {
\t\treturn 0, false, nil
\t}
\tadjusted := *cfg.MaxTokens
\tif adjusted <= 0 {
\t\tcfg.MaxTokens = nil
\t\treturn 0, false, nil
\t}
\tif adjusted > maxOutput {
\t\tadjusted = maxOutput
\t}
\tremainingContext := contextLength - usedTokenCount
\tif adjusted > remainingContext {
\t\tadjusted = remainingContext
\t}
\tcfg.MaxTokens = &adjusted
\treturn adjusted, true, nil
}

// Compatibility wrapper for existing callers/tests that historically used one
// value for both constraints. New chat-pipeline code should use
// clampChatConfigBudgets with the separately resolved limits.
func clampChatConfigMaxTokens(cfg *modelModule.ChatConfig, modelMaxTokens, usedTokenCount int) (int, bool, error) {
\treturn clampChatConfigBudgets(cfg, modelMaxTokens, modelMaxTokens, usedTokenCount)
}
'''
    text = replace_once(text, old_helper, new_helper, "completion clamp helper")
    path.write_text(text, encoding="utf-8")


def patch_tests(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    anchor = "\n// stubHarness installs a fake harnessRetriever returning the given answer and\n"
    if text.count(anchor) != 1:
        raise RuntimeError(f"test anchor: expected one match, found {text.count(anchor)}")
    test = r'''
func TestContextMeshD24SeparatesContextAndOutputBudgets(t *testing.T) {
\tt.Run("generation cap is independent of large context window", func(t *testing.T) {
\t\trequested := 50000
\t\tcfg := &modelModule.ChatConfig{MaxTokens: &requested}
\t\tadjusted, ok, err := clampChatConfigBudgets(cfg, 128000, 16384, 20000)
\t\tif err != nil {
\t\t\tt.Fatalf("clampChatConfigBudgets returned error: %v", err)
\t\t}
\t\tif !ok || adjusted != 16384 {
\t\t\tt.Fatalf("adjusted=%d ok=%t, want 16384,true", adjusted, ok)
\t\t}
\t})

\tt.Run("remaining context can be tighter than generation cap", func(t *testing.T) {
\t\trequested := 16000
\t\tcfg := &modelModule.ChatConfig{MaxTokens: &requested}
\t\tadjusted, ok, err := clampChatConfigBudgets(cfg, 128000, 16384, 120000)
\t\tif err != nil {
\t\t\tt.Fatalf("clampChatConfigBudgets returned error: %v", err)
\t\t}
\t\tif !ok || adjusted != 8000 {
\t\t\tt.Fatalf("adjusted=%d ok=%t, want 8000,true", adjusted, ok)
\t\t}
\t})

\tt.Run("context exhaustion fails even when output cap remains", func(t *testing.T) {
\t\trequested := 1000
\t\tcfg := &modelModule.ChatConfig{MaxTokens: &requested}
\t\tif adjusted, ok, err := clampChatConfigBudgets(cfg, 128000, 16384, 128000); err == nil {
\t\t\tt.Fatalf("expected context-capacity error, got adjusted=%d ok=%t", adjusted, ok)
\t\t}
\t})
}
'''
    text = text.replace(anchor, "\n" + test + anchor, 1)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the minimal RAGFlow D24 budget-separation patch.")
    parser.add_argument("ragflow", type=Path, help="RAGFlow checkout root")
    args = parser.parse_args()
    root = args.ragflow
    patch_chat_pipeline(root / "internal/service/chat_pipeline.go")
    patch_tests(root / "internal/service/chat_pipeline_test.go")
    print("PATCHED_D24 separate_context_and_output_budgets")


if __name__ == "__main__":
    main()
