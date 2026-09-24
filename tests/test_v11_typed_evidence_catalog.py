from pathlib import Path

from fastapi.testclient import TestClient

import contextmesh.api as api_module
from contextmesh.evidence import evidence_kind_counts, render_typed_evidence
from contextmesh.ingest import ingest_paths
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.store import FileContextStore


class RelevantJudge:
    def inspect(self, question, answer, block, notes):
        return "Policy evidence materially changes the answer.", True

    def reduce_notes(self, question, answer, notes, level):
        return " | ".join(notes)

    def finalize(self, state):
        assert render_typed_evidence(state.evidence)
        return 91.0, "typed evidence present"


def make_corpus(tmp_path: Path):
    src = tmp_path / "policy.md"
    src.write_text(
        "# Policy\n"
        "The launch date is 2026-10-15. Availability must remain above 99.95%. "
        "Unless emergency maintenance is declared, the service must not be disabled. "
        "However, the candidate answer says downtime is always allowed.\n",
        encoding="utf-8",
    )
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([src], store, "corp_v11", window_chars=180, overlap_chars=0)
    return store, manifest


def test_sqlite_catalog_ranks_without_filtering_coverage(tmp_path: Path):
    store, manifest = make_corpus(tmp_path)
    stats = store.catalog_stats(manifest.corpus_id)
    assert stats["backend"] in {"sqlite-fts5", "sqlite-lexical"}
    assert stats["indexed_blocks"] >= manifest.total_blocks
    assert stats["processable_blocks"] == manifest.required_blocks
    assert stats["ready"] is True

    from contextmesh.reader import CorpusReader

    reader = CorpusReader(store, manifest.corpus_id)
    ordered = reader.lexical_order("99.95 availability")
    assert set(ordered) == set(reader.required_ids)
    assert len(ordered) == len(reader.required_ids)
    assert "99.95" in reader.read(ordered[0]).text


def test_typed_evidence_preserves_critical_atoms(tmp_path: Path):
    store, manifest = make_corpus(tmp_path)
    result = ProgressiveEvaluator(store, RelevantJudge(), reduction_batch_size=4).evaluate(
        manifest.corpus_id,
        "Is the candidate answer compliant?",
        "Downtime is always allowed.",
    )
    assert result.complete is True
    assert result.evidence_atoms > 0
    counts = result.evidence_kind_counts
    assert counts.get("date", 0) >= 1
    assert counts.get("number", 0) >= 1
    assert counts.get("exception", 0) >= 1
    assert counts.get("requirement", 0) >= 1
    assert counts.get("contradiction", 0) >= 1
    assert evidence_kind_counts(result.evidence) == counts
    rendered = render_typed_evidence(result.evidence)
    assert "2026-10-15" in rendered
    assert "99.95" in rendered
    assert "block=" in rendered


def test_catalog_and_job_api_expose_v11_state(tmp_path: Path, monkeypatch):
    store, manifest = make_corpus(tmp_path)
    monkeypatch.setattr(api_module, "STORE", store)
    client = TestClient(api_module.app)

    catalog = client.get(f"/api/corpora/{manifest.corpus_id}/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["indexed_blocks"] >= manifest.total_blocks
    assert catalog.json()["processable_blocks"] == manifest.required_blocks
    assert "never coverage eligibility" in catalog.json()["policy"]

    search = client.get(
        f"/api/corpora/{manifest.corpus_id}/search",
        params={"q": "emergency maintenance", "limit": 10},
    )
    assert search.status_code == 200
    body = search.json()
    assert body["blocks"]
    assert body["catalog"]["indexed_blocks"] >= manifest.total_blocks
    assert body["catalog"]["processable_blocks"] == manifest.required_blocks
    assert "never coverage eligibility" in body["ranking_policy"]


def test_v11_workspace_surfaces_catalog_and_typed_evidence():
    client = TestClient(api_module.app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.11.0"
    page = client.get("/")
    assert page.status_code == 200
    assert "Typed evidence inspector" in page.text
    assert "Catalog" in page.text
