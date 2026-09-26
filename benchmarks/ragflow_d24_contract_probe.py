from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect RAGFlow D24 context/output budget binding.")
    parser.add_argument("ragflow", type=Path)
    parser.add_argument("--expect", choices=["broken", "fixed"], required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    root = args.ragflow
    catalog = json.loads((root / "conf/models/openai.json").read_text(encoding="utf-8"))
    models = catalog["models"] if isinstance(catalog, dict) else catalog
    gpt4o = next(m for m in models if m.get("name") == "gpt-4o")
    context_length = int(gpt4o["context_length"])
    max_output = int(gpt4o["max_output"])

    solver = (root / "internal/service/model_solver.go").read_text(encoding="utf-8")
    pipeline = (root / "internal/service/chat_pipeline.go").read_text(encoding="utf-8")

    checks = {
        "solver_has_context_length": "ContextLength int" in solver and "ContextLength: contextLength" in solver,
        "solver_has_separate_max_tokens": "MaxTokens     int" in solver and "MaxTokens:     maxTokens" in solver,
        "pipeline_exposes_context_length": pipeline.count('cfg["context_length"] = target.ContextLength') >= 2,
        "pipeline_reads_context_length": 'llmModelConfig["context_length"]' in pipeline and "modelContextLength" in pipeline,
        "knowledge_uses_context_length": "s.kbPrompt(kbinfos, modelContextLength)" in pipeline,
        "message_fit_uses_context_length": "messageFitIn(llmMessages, int(float64(modelContextLength)*0.95))" in pipeline,
        "completion_clamp_separates_budgets": "clampChatConfigBudgets(chatCfg, modelContextLength, modelMaxTokens, usedTokenCount+citationTokens)" in pipeline,
        "old_fit_uses_output_cap": "messageFitIn(llmMessages, int(float64(modelMaxTokens)*0.95))" in pipeline,
    }

    fixed = all(
        checks[name]
        for name in [
            "solver_has_context_length",
            "solver_has_separate_max_tokens",
            "pipeline_exposes_context_length",
            "pipeline_reads_context_length",
            "knowledge_uses_context_length",
            "message_fit_uses_context_length",
            "completion_clamp_separates_budgets",
        ]
    ) and not checks["old_fit_uses_output_cap"]

    status = "fixed" if fixed else "broken"
    result = {
        "kind": "contextmesh-ragflow-d24-contract-probe",
        "status": status,
        "catalog": {
            "provider": "OpenAI",
            "model": "gpt-4o",
            "context_length": context_length,
            "max_output": max_output,
            "context_to_output_ratio": context_length / max_output,
        },
        "checks": checks,
        "broken_effective_fit_budget_before_95_percent": max_output if status == "broken" else None,
        "fixed_effective_fit_budget_before_95_percent": context_length if status == "fixed" else None,
    }

    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    if status != args.expect:
        raise SystemExit(f"expected {args.expect}, observed {status}")


if __name__ == "__main__":
    main()
