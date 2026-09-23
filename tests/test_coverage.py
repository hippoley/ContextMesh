from pathlib import Path
from contextmesh.ingest import ingest_paths
from contextmesh.judges import HeuristicJudge
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.store import FileContextStore


def test_full_coverage_even_when_order_is_partial(tmp_path: Path):
    f = tmp_path / "doc.txt"
    f.write_text("alpha " * 5000 + "critical exception 42 " + "omega " * 5000)
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([f], store, "corp_test", window_chars=3000, overlap_chars=100)
    assert manifest.total_blocks > 1
    # Passing a single preferred block must not filter out the rest.
    result = ProgressiveEvaluator(store, HeuristicJudge()).evaluate(
        "corp_test", "critical exception", "answer", order=[manifest.block_ids[-1]]
    )
    assert result.complete is True
    assert result.coverage == 1.0
    assert result.visited_blocks == manifest.total_blocks
