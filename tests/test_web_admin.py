from pathlib import Path

from fastapi.testclient import TestClient

import contextmesh.api as api_module
from contextmesh.models import EvaluationCheckpoint, EvaluationState
from contextmesh.store import FileContextStore


def test_workspace_and_admin_pages_exist():
    client = TestClient(api_module.app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Read everything. Score once." in r.text
    r = client.get("/admin")
    assert r.status_code == 200
    assert "Context control plane." in r.text
    r = client.get("/static/contextmesh.css")
    assert r.status_code == 200
    assert "--accent" in r.text


def test_store_lists_and_deletes_corpora(tmp_path: Path):
    from contextmesh.ingest import ingest_paths

    store = FileContextStore(tmp_path / "store")
    doc = tmp_path / "a.md"
    doc.write_text("# A\nhello world", encoding="utf-8")
    manifest = ingest_paths([doc], store, "corp_test")
    assert [x.corpus_id for x in store.list_manifests()] == ["corp_test"]

    state = EvaluationState(corpus_id="corp_test", question="hello?", answer="hello")
    state.visited = set(manifest.coverage_ids())
    store.put_checkpoint(
        EvaluationCheckpoint(
            job_id="job_test",
            corpus_id="corp_test",
            ordered_block_ids=manifest.coverage_ids(),
            cursor=len(manifest.coverage_ids()),
            state=state,
            complete=True,
        )
    )
    assert [x.job_id for x in store.list_checkpoints("corp_test")] == ["job_test"]
    assert store.delete_corpus("corp_test") is True
    assert store.list_manifests() == []
    assert store.delete_corpus("corp_test") is False
