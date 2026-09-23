from pathlib import Path

from contextmesh.audit import audit_corpus
from contextmesh.ingest import ingest_paths
from contextmesh.store import FileContextStore


def test_integrity_audit_passes_for_valid_text_corpus(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("needle 42", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    ingest_paths([p], store, "audit-ok")
    report = audit_corpus(store, "audit-ok")
    assert report.ok is True
    assert report.required_blocks == 1
    assert report.checked_blocks == 1
    assert report.issues == []


def test_integrity_audit_catches_deleted_media_payload(tmp_path: Path):
    from PIL import Image

    p = tmp_path / "x.png"
    Image.new("RGB", (16, 16), "white").save(p)
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([p], store, "audit-media")
    block = store.get_block("audit-media", manifest.required_block_ids[0])
    media = Path(block.metadata.get("media_path") or block.source.path)
    media.unlink()

    report = audit_corpus(store, "audit-media")
    assert report.ok is False
    assert any(x.code == "missing_media_payload" for x in report.issues)
