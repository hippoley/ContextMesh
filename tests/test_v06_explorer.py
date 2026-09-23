from pathlib import Path

from fastapi.testclient import TestClient

import contextmesh.api as api_module
from contextmesh.ingest import ingest_paths
from contextmesh.store import FileContextStore


def test_context_explorer_endpoints(tmp_path: Path, monkeypatch):
    store = FileContextStore(tmp_path / "store")
    doc = tmp_path / "guide.md"
    doc.write_text("# Safety\nNever skip the coverage gate.\n\n# Billing\nInvoices are monthly.", encoding="utf-8")
    manifest = ingest_paths([doc], store, "corp_explorer")
    monkeypatch.setattr(api_module, "STORE", store)
    client = TestClient(api_module.app)

    page = client.get(f"/api/corpora/{manifest.corpus_id}/blocks?limit=100")
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == manifest.required_blocks
    assert len(body["blocks"]) == manifest.required_blocks

    search = client.get(f"/api/corpora/{manifest.corpus_id}/search", params={"q": "coverage gate"})
    assert search.status_code == 200
    blocks = search.json()["blocks"]
    assert blocks
    assert any("coverage gate" in b["text"].lower() for b in blocks)

    block_id = blocks[0]["id"]
    detail = client.get(f"/corpora/{manifest.corpus_id}/blocks/{block_id}")
    assert detail.status_code == 200
    assert detail.json()["processable"] is True


def test_workspace_contains_context_explorer():
    client = TestClient(api_module.app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Context Explorer" in r.text
    assert "contextSearch" in r.text
