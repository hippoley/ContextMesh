from pathlib import Path
from contextmesh.ingest import ingest_paths
from contextmesh.store import FileContextStore


def test_blocks_keep_neighbors(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("x" * 9000)
    store = FileContextStore(tmp_path / "store")
    m = ingest_paths([f], store, "c", window_chars=3000, overlap_chars=100)
    first = store.get_block("c", m.block_ids[0])
    second = store.get_block("c", m.block_ids[1])
    assert first.next_id == second.id
    assert second.prev_id == first.id
