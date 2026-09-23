from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.judges import HeuristicJudge
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.store import FileContextStore


def test_progressive_run_can_pause_and_resume(tmp_path: Path):
    f = tmp_path / "doc.txt"
    f.write_text("alpha " * 3000 + "critical exception 42 " + "omega " * 3000)
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([f], store, "corp", window_chars=2000, overlap_chars=100)
    evaluator = ProgressiveEvaluator(store, HeuristicJudge())

    partial = evaluator.evaluate("corp", "critical exception", "answer", max_blocks=2)
    assert partial.complete is False
    assert 0 < partial.coverage < 1
    assert partial.score is None
    assert partial.job_id

    final = evaluator.evaluate(
        "corp",
        "critical exception",
        "answer",
        job_id=partial.job_id,
        resume=True,
    )
    assert final.complete is True
    assert final.coverage == 1.0
    assert final.visited_blocks == manifest.total_blocks
