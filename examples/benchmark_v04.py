from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from contextmesh.benchmark import ScorePreservationBenchmark
from contextmesh.ingest import ingest_paths
from contextmesh.judges import HeuristicJudge
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.store import FileContextStore


class LatencyJudge(HeuristicJudge):
    def __init__(self, delay: float):
        self.delay = delay

    def inspect(self, question, answer, block, notes):
        time.sleep(self.delay)
        return super().inspect(question, answer, block, notes)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--records", type=int, default=500)
    p.add_argument("--delay-ms", type=float, default=2.0)
    args = p.parse_args()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "synthetic.txt"
        src.write_text(
            "".join(f"record {i:05d}: important enterprise fact value={i} {'x'*80}\n" for i in range(args.records)),
            encoding="utf-8",
        )
        store = FileContextStore(root / "store")
        manifest = ingest_paths([src], store, "bench", window_chars=120, overlap_chars=0)

        timings = {}
        for workers in (1, 8):
            judge = LatencyJudge(args.delay_ms / 1000.0)
            evaluator = ProgressiveEvaluator(
                store,
                judge,
                max_workers=workers,
                execution_batch_size=max(16, workers * 8),
                reduction_batch_size=16,
            )
            start = time.perf_counter()
            result = evaluator.evaluate("bench", "important enterprise", "candidate")
            timings[workers] = time.perf_counter() - start
            assert result.complete

        judge = HeuristicJudge()
        report = ScorePreservationBenchmark(
            ProgressiveEvaluator(store, judge, max_workers=8, reduction_batch_size=16),
            judge,
            max_direct_chars=1_000_000,
            tolerance=0.0,
        ).run("bench", "important enterprise", "candidate")

        print(f"required_blocks={manifest.required_blocks}")
        print(f"sequential_seconds={timings[1]:.4f}")
        print(f"parallel_8_seconds={timings[8]:.4f}")
        print(f"speedup={timings[1] / timings[8]:.2f}x")
        print(f"score_drift={report.absolute_drift:.4f}")
        print(f"coverage={report.coverage:.4f}")


if __name__ == "__main__":
    main()
