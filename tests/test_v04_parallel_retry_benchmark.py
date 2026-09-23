import time
from pathlib import Path

from contextmesh.benchmark import ScorePreservationBenchmark
from contextmesh.ingest import ingest_paths
from contextmesh.judges import HeuristicJudge
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.store import FileContextStore


class DelayedJudge(HeuristicJudge):
    def inspect(self, question, answer, block, notes):
        # Deliberately make earlier/later completions differ from corpus order.
        delay = (int(block.source.locator.get("char_start", 0)) % 7) * 0.0005
        time.sleep(delay)
        return f"{block.id}: ordered-evidence", True


class FlakyJudge(HeuristicJudge):
    def __init__(self):
        self.calls = {}

    def inspect(self, question, answer, block, notes):
        n = self.calls.get(block.id, 0) + 1
        self.calls[block.id] = n
        if n == 1:
            raise RuntimeError("transient")
        return f"{block.id}: recovered", True


class OneBlockFailsJudge(HeuristicJudge):
    def __init__(self, fail_id):
        self.fail_id = fail_id

    def inspect(self, question, answer, block, notes):
        if block.id == self.fail_id:
            raise RuntimeError("persistent")
        return f"{block.id}: ok", True


def _corpus(tmp_path: Path, blocks: int = 20):
    src = tmp_path / "corpus.txt"
    src.write_text("".join(f"block-{i:04d} important fact {'x'*80}\n" for i in range(blocks)), encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([src], store, "c", window_chars=120, overlap_chars=0)
    return store, manifest


def test_parallel_merge_is_deterministic(tmp_path: Path):
    store, manifest = _corpus(tmp_path, 40)
    result = ProgressiveEvaluator(
        store, DelayedJudge(), max_workers=8, execution_batch_size=16, reduction_batch_size=8
    ).evaluate("c", "important", "answer", order=manifest.required_block_ids)
    assert result.complete is True
    assert result.execution_mode == "parallel"
    assert [e.block_id for e in result.evidence] == manifest.required_block_ids


def test_transient_failures_retry_without_losing_coverage(tmp_path: Path):
    store, manifest = _corpus(tmp_path, 12)
    judge = FlakyJudge()
    result = ProgressiveEvaluator(store, judge, max_workers=4, retry_attempts=2).evaluate(
        "c", "important", "answer"
    )
    assert result.complete is True
    assert result.coverage == 1.0
    assert result.failed_blocks == 0
    assert result.inspection_attempts == manifest.required_blocks * 2


def test_persistent_failure_blocks_score_then_resume_recovers(tmp_path: Path):
    store, manifest = _corpus(tmp_path, 10)
    fail_id = manifest.required_block_ids[2]
    partial = ProgressiveEvaluator(
        store, OneBlockFailsJudge(fail_id), max_workers=4, retry_attempts=2
    ).evaluate("c", "important", "answer")
    assert partial.complete is False
    assert partial.score is None
    assert partial.failed_blocks == 1
    assert partial.visited_blocks == manifest.required_blocks - 1

    final = ProgressiveEvaluator(store, HeuristicJudge(), max_workers=2).evaluate(
        "c", "important", "answer", job_id=partial.job_id, resume=True
    )
    assert final.complete is True
    assert final.coverage == 1.0
    assert final.failed_blocks == 0
    assert final.visited_blocks == manifest.required_blocks


def test_score_preservation_benchmark_has_zero_drift_for_reference_judge(tmp_path: Path):
    store, manifest = _corpus(tmp_path, 18)
    judge = HeuristicJudge()
    evaluator = ProgressiveEvaluator(store, judge, max_workers=4, reduction_batch_size=4)
    report = ScorePreservationBenchmark(evaluator, judge, tolerance=0.0).run(
        "c", "important", "answer"
    )
    assert report.coverage == 1.0
    assert report.total_blocks == manifest.required_blocks
    assert report.absolute_drift == 0.0
    assert report.passed is True


def test_thousand_block_stress_keeps_final_context_bounded(tmp_path: Path):
    store, manifest = _corpus(tmp_path, 1000)
    judge = HeuristicJudge()
    result = ProgressiveEvaluator(
        store,
        judge,
        max_workers=8,
        execution_batch_size=64,
        reduction_batch_size=16,
    ).evaluate("c", "important", "answer")
    assert manifest.required_blocks >= 800
    assert result.complete is True
    assert result.coverage == 1.0
    assert result.reduced_context_items <= 16
    assert result.failed_blocks == 0
