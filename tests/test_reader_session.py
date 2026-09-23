from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.reader import CorpusReader
from contextmesh.rlm_tools import ReaderSession
from contextmesh.store import FileContextStore


def test_reader_session_exposes_coverage_and_next_unvisited(tmp_path: Path):
    f = tmp_path / "doc.txt"
    f.write_text("alpha " * 1000)
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([f], store, "corp", window_chars=500, overlap_chars=0)
    session = ReaderSession(CorpusReader(store, "corp"))

    first = session.next_unvisited()
    assert first is not None
    session.read(first)
    status = session.coverage()
    assert status["visited"] == 1
    assert status["required"] == manifest.total_blocks
    assert status["complete"] is (manifest.total_blocks == 1)
