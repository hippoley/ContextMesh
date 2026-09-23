from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.store import FileContextStore


def test_manifest_tracks_bytes_and_modalities(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.csv"
    a.write_text("hello", encoding="utf-8")
    b.write_text("x,y\n1,2\n", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    m = ingest_paths([a,b], store, "c")
    assert m.total_bytes == a.stat().st_size + b.stat().st_size
    assert m.modality_counts["text"] >= 1
    assert m.modality_counts["table"] >= 1
