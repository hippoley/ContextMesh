from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.reader import CorpusReader
from contextmesh.store import FileContextStore


def test_lexical_ranking_is_scheduling_only(tmp_path: Path):
    f = tmp_path / "doc.txt"
    f.write_text("boring " * 500 + "needle critical fact " + "boring " * 500)
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([f], store, "corp", window_chars=1000, overlap_chars=0)
    reader = CorpusReader(store, "corp")
    order = reader.lexical_order("needle")
    assert set(order) == set(manifest.block_ids)
    assert "needle" in reader.read(order[0]).text
