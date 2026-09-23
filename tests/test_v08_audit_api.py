from pathlib import Path

from fastapi.testclient import TestClient

import contextmesh.api as api
from contextmesh.ingest import ingest_paths
from contextmesh.store import FileContextStore


def test_corpus_audit_api(tmp_path: Path, monkeypatch):
    store = FileContextStore(tmp_path / "store")
    monkeypatch.setattr(api, "STORE", store)
    p = tmp_path / "a.txt"
    p.write_text("needle", encoding="utf-8")
    ingest_paths([p], store, "c")
    client = TestClient(api.app)
    r = client.get("/api/corpora/c/audit")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["checked_blocks"] == 1
