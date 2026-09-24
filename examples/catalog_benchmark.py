from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from time import perf_counter

from contextmesh.catalog import SQLiteContextCatalog
from contextmesh.models import BlockKind, ContextBlock, Modality, SourceRef


def run(blocks: int = 100_000, batch_size: int = 5_000) -> dict:
    needle_positions = {17, max(17, blocks // 2 - 1889), max(17, blocks - 1)}
    with tempfile.TemporaryDirectory(prefix="contextmesh-catalog-") as tmp:
        catalog = SQLiteContextCatalog(Path(tmp) / "catalog.sqlite3")
        started = perf_counter()
        for start in range(0, blocks, batch_size):
            batch: list[ContextBlock] = []
            for i in range(start, min(start + batch_size, blocks)):
                text = f"enterprise policy block {i} ordinary content"
                if i in needle_positions:
                    text += " rare-needle-zenith unless maintenance 99.95 percent"
                batch.append(
                    ContextBlock(
                        id=f"b{i:07d}",
                        corpus_id="catalog-benchmark",
                        modality=Modality.TEXT,
                        kind=BlockKind.CONTENT,
                        text=text,
                        source=SourceRef(
                            asset_id=f"asset-{i // 1000}",
                            path=f"asset-{i // 1000}.txt",
                            locator={"row": i},
                        ),
                    )
                )
            catalog.upsert_many(batch)
        index_seconds = perf_counter() - started

        started = perf_counter()
        hits = catalog.search("catalog-benchmark", "rare needle zenith", limit=20)
        query_seconds = perf_counter() - started
        return {
            "blocks": blocks,
            "batch_size": batch_size,
            "index_seconds": round(index_seconds, 4),
            "query_ms": round(query_seconds * 1000, 4),
            "hits": hits,
            "stats": catalog.stats("catalog-benchmark"),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ContextMesh SQLite/FTS catalog indexing and search")
    parser.add_argument("--blocks", type=int, default=100_000)
    parser.add_argument("--batch-size", type=int, default=5_000)
    args = parser.parse_args()
    print(json.dumps(run(args.blocks, args.batch_size), indent=2))


if __name__ == "__main__":
    main()
