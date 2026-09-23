from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

import contextmesh.api as api_module
import contextmesh.rich_ingest as rich_ingest
from contextmesh.store import FileContextStore


def test_async_partial_ingest_and_ingest_blocked_evaluation(tmp_path: Path, monkeypatch):
    from docx import Document

    docx_path = tmp_path / "partial.docx"
    doc = Document()
    doc.add_paragraph("All addressable text was read, but layout rendering is unavailable.")
    doc.save(docx_path)

    # Force a known unresolved visual/layout channel.
    monkeypatch.setattr(rich_ingest, "_convert_office_to_pdf", lambda *args, **kwargs: None)
    store = FileContextStore(tmp_path / "store")
    monkeypatch.setattr(api_module, "STORE", store)
    monkeypatch.setattr(api_module, "UPLOAD_ROOT", tmp_path / "uploads")
    client = TestClient(api_module.app)

    with docx_path.open("rb") as f:
        r = client.post("/api/ingest-jobs", files=[("files", ("partial.docx", f.read(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))])
    assert r.status_code == 200
    ingest = r.json()
    job = None
    for _ in range(200):
        job = client.get(f"/api/ingest-jobs/{ingest['job_id']}").json()
        if job["status"] in {"complete", "partial", "failed"}:
            break
        time.sleep(0.01)
    assert job is not None
    assert job["status"] == "partial"
    assert job["manifest"]["coverage_ready"] is False
    assert job["manifest"]["semantic_coverage"] < 1.0

    r = client.post("/api/evaluation-jobs", json={
        "corpus_id": ingest["corpus_id"],
        "question": "Was the corpus completely understood?",
        "answer": "Yes",
    })
    assert r.status_code == 200
    eval_job = r.json()
    detail = None
    for _ in range(200):
        rr = client.get(f"/api/jobs/{ingest['corpus_id']}/{eval_job['job_id']}")
        if rr.status_code == 200:
            detail = rr.json()
            if detail["status"] in {"complete", "failed", "blocked", "ingest_blocked"}:
                break
        time.sleep(0.01)
    assert detail is not None
    assert detail["status"] == "ingest_blocked"
    assert detail["coverage"] == 1.0
    assert detail["score"] is None
    assert detail["ingest_ready"] is False
