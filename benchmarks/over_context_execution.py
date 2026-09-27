from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.semantics import DecisionBundle, ExecutionContract
from contextmesh.store import FileContextStore


MARKER = "DECISIVE_EXCEPTION_17_4"
EXCEPTION_TEXT = (
    f"Except where Section 17.4 applies, identified by {MARKER}, "
    "termination requires sixty days written notice."
)


class BudgetJudge:
    """Deterministic judge used to verify execution shape, not model intelligence."""

    supports_neighbor_context = False

    def __init__(self, max_request_chars: int):
        self.max_request_chars = max_request_chars
        self.calls = 0
        self.max_observed_request_chars = 0

    def inspect(self, question, answer, block, notes):
        request_chars = (
            len(question)
            + len(answer)
            + len(block.text or "")
            + sum(len(note) for note in notes)
        )
        self.max_observed_request_chars = max(
            self.max_observed_request_chars, request_chars
        )
        if request_chars > self.max_request_chars:
            raise RuntimeError(
                f"simulated model context exceeded: {request_chars}>{self.max_request_chars}"
            )
        self.calls += 1
        if MARKER in (block.text or ""):
            return EXCEPTION_TEXT, True
        return f"{block.id}: inspected; no decisive exception", False

    def reduce_notes(self, question, answer, notes, level):
        # Explanatory channel stays deliberately tiny. The decisive exception must
        # survive through typed evidence / DecisionBundle, not by relying on this text.
        return f"L{level}: inspected_findings={len(notes)}"

    def finalize(self, state):
        bundle = DecisionBundle.model_validate(state.decision_bundle or {})
        exception_text = "\n".join(unit.text for unit in bundle.exceptions)
        if MARKER not in exception_text:
            raise RuntimeError("decisive exception was lost before final judgment")
        return 100.0, "decisive exception survived into DecisionBundle"


def build_corpus(root: Path, *, files: int, target_tokens: int, chars_per_token: int) -> list[Path]:
    target_chars = target_tokens * chars_per_token
    per_file = target_chars // files
    filler = (
        "Ordinary operational clause: service delivery continues under the standard "
        "commercial schedule unless a separately stated exception applies. "
    )

    paths: list[Path] = []
    for index in range(files):
        path = root / f"document-{index + 1:02d}.txt"
        chunks: list[str] = []
        current = 0
        while current < per_file:
            chunks.append(filler)
            current += len(filler)

        # Put the decisive exception in file 11 (or the last available file), around
        # the middle rather than at an easy head/tail boundary.
        if index == min(10, files - 1):
            midpoint = len(chunks) // 2
            chunks.insert(midpoint, EXCEPTION_TEXT + "\n")

        path.write_text("".join(chunks)[: per_file + len(EXCEPTION_TEXT) + 1], encoding="utf-8")
        paths.append(path)
    return paths


def run_benchmark(
    *,
    target_tokens: int,
    files: int,
    simulated_context_tokens: int,
    chars_per_token: int,
    window_chars: int,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="contextmesh-over-context-") as tmp:
        root = Path(tmp)
        paths = build_corpus(
            root,
            files=files,
            target_tokens=target_tokens,
            chars_per_token=chars_per_token,
        )
        store = FileContextStore(root / "store")
        manifest = ingest_paths(
            paths,
            store,
            "corp_over_context",
            window_chars=window_chars,
            overlap_chars=200,
        )

        simulated_context_chars = simulated_context_tokens * chars_per_token
        judge = BudgetJudge(max_request_chars=simulated_context_chars)
        evaluator = ProgressiveEvaluator(
            store,
            judge,
            reduction_batch_size=16,
            max_workers=8,
            execution_batch_size=16,
        )
        contract = ExecutionContract.full_coverage(manifest.coverage_ids())

        # A one-item preferred order is intentionally incomplete. ContextMesh may use
        # it for scheduling, but must append every required block for eligibility.
        result = evaluator.evaluate(
            manifest.corpus_id,
            "Does any exception change the termination rule?",
            "No exception changes the rule.",
            order=[manifest.coverage_ids()[0]],
            contract=contract,
        )

        bundle = DecisionBundle.model_validate(result.decision_bundle or {})
        marker_survived = any(MARKER in unit.text for unit in bundle.exceptions)
        corpus_chars = sum(path.stat().st_size for path in paths)
        estimated_tokens = corpus_chars // chars_per_token

        report = {
            "schema_version": 1,
            "fixture": "multi-file-over-context-full-coverage",
            "files": files,
            "corpus_chars": corpus_chars,
            "estimated_corpus_tokens": estimated_tokens,
            "simulated_model_context_tokens": simulated_context_tokens,
            "corpus_to_context_ratio": round(
                estimated_tokens / simulated_context_tokens, 3
            ),
            "window_chars": window_chars,
            "required_blocks": manifest.required_blocks,
            "visited_blocks": result.visited_blocks,
            "coverage": result.coverage,
            "complete": result.complete,
            "judge_calls": judge.calls,
            "max_observed_request_chars": judge.max_observed_request_chars,
            "max_request_chars": simulated_context_chars,
            "request_budget_respected": (
                judge.max_observed_request_chars <= simulated_context_chars
            ),
            "execution_contract_mode": result.execution_contract_mode,
            "transition_receipts": result.transition_receipts,
            "transition_chain_valid": result.transition_chain_valid,
            "semantic_units": result.semantic_units,
            "reduction_receipts": result.reduction_receipts,
            "decision_bundle_exceptions": len(bundle.exceptions),
            "decisive_exception_survived": marker_survived,
            "score": result.score,
        }

        required_truths = [
            report["estimated_corpus_tokens"] >= target_tokens,
            report["estimated_corpus_tokens"] > simulated_context_tokens,
            report["coverage"] == 1.0,
            report["visited_blocks"] == report["required_blocks"],
            report["complete"] is True,
            report["request_budget_respected"] is True,
            report["execution_contract_mode"] == "full-coverage",
            report["transition_chain_valid"] is True,
            report["decisive_exception_survived"] is True,
        ]
        if not all(required_truths):
            raise RuntimeError("over-context contract failed: " + json.dumps(report, indent=2))

        return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-tokens", type=int, default=1_100_000)
    parser.add_argument("--files", type=int, default=12)
    parser.add_argument("--simulated-context-tokens", type=int, default=16_000)
    parser.add_argument("--chars-per-token", type=int, default=4)
    parser.add_argument("--window-chars", type=int, default=12_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = run_benchmark(
        target_tokens=args.target_tokens,
        files=args.files,
        simulated_context_tokens=args.simulated_context_tokens,
        chars_per_token=args.chars_per_token,
        window_chars=args.window_chars,
    )
    payload = json.dumps(report, indent=2, sort_keys=True)
    print("OVER_CONTEXT_CONTRACT_OK")
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
