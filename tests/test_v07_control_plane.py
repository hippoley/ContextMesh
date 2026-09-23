from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

import contextmesh.api as api_module
from contextmesh.events import EventBus
from contextmesh.explorer import build_explorer_groups
from contextmesh.ingest import ingest_paths
from contextmesh.models import ModelRoute
from contextmesh.observability import parse_prometheus
from contextmesh.store import FileContextStore


def test_event_bus_broadcasts():
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish("evaluation", {"job_id": "j1", "coverage": 0.5})
    item = sub.queue.get(timeout=0.2)
    assert item["event"] == "evaluation"
    assert item["coverage"] == 0.5
    bus.unsubscribe(sub.id)


def test_prometheus_parser_sums_labelled_samples():
    text = """
# HELP x test
vllm:prefix_cache_queries{worker="a"} 100
vllm:prefix_cache_queries{worker="b"} 50
vllm:prefix_cache_hits{worker="a"} 40
vllm:prefix_cache_hits{worker="b"} 35
"""
    m = parse_prometheus(text)
    assert m["vllm:prefix_cache_queries"] == 150
    assert m["vllm:prefix_cache_hits"] == 75


def test_model_routes_roundtrip(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    route = ModelRoute(id="local", label="Local", base_url="http://localhost:8000/v1", model="qwen")
    store.upsert_model_route(route)
    assert store.list_model_routes()[0].id == "local"
    assert store.delete_model_route("local") is True
    assert store.list_model_routes() == []


def test_explorer_groups_rows_and_sections(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    ingest_paths([csv], store, "corp_groups")
    groups = build_explorer_groups(store, "corp_groups")
    assert groups
    assert groups[0].kind == "rows"
    assert groups[0].required_blocks >= 1


def test_async_ingest_and_evaluation_jobs(tmp_path: Path, monkeypatch):
    store = FileContextStore(tmp_path / "store")
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(api_module, "STORE", store)
    monkeypatch.setattr(api_module, "UPLOAD_ROOT", upload_root)
    client = TestClient(api_module.app)

    r = client.post(
        "/api/ingest-jobs",
        files=[
            ("files", ("policy.md", b"# Policy\nCoverage must be complete.", "text/markdown")),
            ("files", ("metrics.csv", b"name,value\ncoverage,100\n", "text/csv")),
        ],
    )
    assert r.status_code == 200
    ingest = r.json()
    for _ in range(100):
        j = client.get(f"/api/ingest-jobs/{ingest['job_id']}").json()
        if j["status"] in {"complete", "failed"}:
            break
        time.sleep(0.02)
    assert j["status"] == "complete"
    assert j["manifest"]["required_blocks"] >= 2

    req = {
        "corpus_id": ingest["corpus_id"],
        "question": "Is coverage complete?",
        "answer": "Yes",
        "max_workers": 2,
    }
    r = client.post("/api/evaluation-jobs", json=req)
    assert r.status_code == 200
    ej = r.json()
    for _ in range(100):
        detail = client.get(f"/api/jobs/{ingest['corpus_id']}/{ej['job_id']}")
        if detail.status_code == 200 and detail.json()["status"] in {"complete", "failed", "blocked"}:
            break
        time.sleep(0.02)
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "complete"
    assert body["coverage"] == 1.0
    assert body["score"] is not None
