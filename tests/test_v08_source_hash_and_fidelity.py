import hashlib
from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.store import FileContextStore


def test_asset_report_records_source_sha256(tmp_path: Path):
    p = tmp_path / "source.txt"
    p.write_bytes(b"immutable-source-42")
    store = FileContextStore(tmp_path / "store")
    m = ingest_paths([p], store, "hash")
    assert m.asset_reports[0].source_sha256 == hashlib.sha256(p.read_bytes()).hexdigest()
