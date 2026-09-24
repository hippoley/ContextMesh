from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from contextmesh.blockstore import SQLiteBlockPayloadStore
from contextmesh.models import BlockKind, ContextBlock, Modality, SourceRef


def make_block(i: int, corpus_id: str) -> ContextBlock:
    return ContextBlock(
        id=f"b{i:09d}",
        corpus_id=corpus_id,
        modality=Modality.TEXT,
        kind=BlockKind.CONTENT,
        text=f"block {i} enterprise payload value={i % 997}",
        source=SourceRef(asset_id=f"asset-{i // 1000}", path=f"asset-{i // 1000}.txt", locator={"row": i}),
        processable=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark the v0.12 SQLite ContextBlock payload backend")
    ap.add_argument("--blocks", type=int, default=100_000)
    ap.add_argument("--batch-size", type=int, default=5_000)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="contextmesh-storage-bench-") as td:
        store = SQLiteBlockPayloadStore(Path(td) / "blocks.sqlite3")
        started = time.perf_counter()
        for start in range(0, args.blocks, args.batch_size):
            stop = min(args.blocks, start + args.batch_size)
            store.put_many(make_block(i, "bench") for i in range(start, stop))
        write_seconds = time.perf_counter() - started

        probes = [0, args.blocks // 4, args.blocks // 2, (args.blocks * 3) // 4, args.blocks - 1]
        ids = [f"b{i:09d}" for i in probes if 0 <= i < args.blocks]
        started = time.perf_counter()
        rows = store.get_many("bench", ids)
        read_seconds = time.perf_counter() - started

        db_size = (Path(td) / "blocks.sqlite3").stat().st_size
        print(json.dumps({
            "blocks": args.blocks,
            "batch_size": args.batch_size,
            "stored_blocks": store.count("bench"),
            "write_seconds": round(write_seconds, 4),
            "write_blocks_per_second": round(args.blocks / write_seconds, 1) if write_seconds else None,
            "probe_reads": len(ids),
            "probe_read_ms": round(read_seconds * 1000, 3),
            "probe_hits": len(rows),
            "database_bytes": db_size,
            "backend": store.backend,
        }, indent=2))


if __name__ == "__main__":
    main()
