from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.store import FileContextStore


class TrackingJudge:
    def __init__(self):
        self.reduce_calls = []
        self.final_context_size = None

    def inspect(self, question, answer, block, notes):
        return f"{block.id}: fact={block.text[:20]}", True

    def reduce_notes(self, question, answer, notes, level):
        self.reduce_calls.append((level, len(notes)))
        return f"L{level}<{len(notes)}> ids=" + ",".join(n.split(':',1)[0] for n in notes)

    def finalize(self, state):
        self.final_context_size = len(state.model_context_notes())
        return 77.0, "ok"


def test_hierarchical_reduction_bounds_final_context(tmp_path: Path):
    src = tmp_path / "big.txt"
    src.write_text("\n".join(f"line {i} important fact" for i in range(500)), encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([src], store, "c", window_chars=120, overlap_chars=0)
    assert manifest.required_blocks > 32

    judge = TrackingJudge()
    result = ProgressiveEvaluator(store, judge, reduction_batch_size=4).evaluate("c", "important", "answer")
    assert result.complete is True
    assert result.coverage == 1.0
    assert judge.reduce_calls
    assert any(level >= 2 for level, _ in judge.reduce_calls)
    assert judge.final_context_size <= 4
    assert result.reduction_nodes > 0
