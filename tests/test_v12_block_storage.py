from pathlib import Path

from fastapi.testclient import TestClient

import contextmesh.api as api_module
from contextmesh import __version__
from contextmesh.ingest import ingest_paths
from contextmesh.models import BlockKind, ContextBlock, CorpusManifest, Modality, SourceRef
from contextmesh.reader import CorpusReader
from contextmesh.store import FileContextStore


def _block(corpus: str, block_id: str, text: str, *, page: int | None = None, modality=Modality.TEXT):
    locator = {} if page is None else {"page": page}
    return ContextBlock(
        id=block_id,
        corpus_id=corpus,
        modality=modality,
        kind=BlockKind.CONTENT if modality == Modality.TEXT else BlockKind.IMAGE,
        text=text,
        source=SourceRef(asset_id="asset-1", path="guide.pdf", locator=locator),
        processable=True,
    )


def _manifest(corpus: str, blocks: list[ContextBlock]) -> CorpusManifest:
    ids = [b.id for b in blocks]
    return CorpusManifest(
        corpus_id=corpus,
        assets=["guide.pdf"],
        block_ids=ids,
        required_block_ids=ids,
        total_blocks=len(ids),
        required_blocks=len(ids),
        total_chars=sum(len(b.text) for b in blocks),
    )


def test_default_store_uses_sqlite_payloads_without_json_per_block(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    blocks = [_block("c", f"b{i}", f"payload {i}") for i in range(5)]
    store.put_blocks(blocks)
    store.put_manifest(_manifest("c", blocks))

    assert store.block_backend == "sqlite"
    assert (store.root / "_blocks.sqlite3").is_file()
    assert not (store.root / "c" / "blocks").exists()
    assert store.get_block("c", "b3").text == "payload 3"
    assert [b.id for b in store.get_blocks("c", ["b4", "b1"])] == ["b4", "b1"]
    stats = store.block_store_stats("c")
    assert stats["backend"] == "sqlite-payload"
    assert stats["stored_blocks"] == 5
    assert stats["ready"] is True


def test_json_backend_remains_supported_and_upgrades_lazily(tmp_path: Path):
    root = tmp_path / "store"
    legacy = FileContextStore(root, block_backend="json")
    src = tmp_path / "legacy.md"
    src.write_text("# One\nlegacy payload\n\n# Two\nsecond payload", encoding="utf-8")
    manifest = ingest_paths([src], legacy, "legacy")
    assert (root / "legacy" / "blocks").exists()

    upgraded = FileContextStore(root, block_backend="sqlite")
    stats = upgraded.ensure_block_store("legacy")
    assert stats["stored_blocks"] >= manifest.required_blocks
    assert stats["legacy_json_blocks"] >= manifest.required_blocks
    assert stats["migrated_blocks"] > 0
    assert upgraded.get_block("legacy", manifest.coverage_ids()[0]).corpus_id == "legacy"


def test_structural_relations_use_catalog_locator_indexes(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    blocks = [
        _block("c", "page1-text", "See page 2 for the exception.", page=1),
        _block("c", "page1-image", "visual description", page=1, modality=Modality.IMAGE),
        _block("c", "page2-text", "Exception: approval is required.", page=2),
    ]
    store.put_blocks(blocks)
    store.put_manifest(_manifest("c", blocks))
    reader = CorpusReader(store, "c")

    related = reader.related("page1-text")
    assert [b.id for b in related] == ["page1-image"]
    refs = reader.references("page1-text")
    assert "page2-text" in [b.id for b in refs]


def test_storage_api_reports_runtime_payload_backend(tmp_path: Path, monkeypatch):
    store = FileContextStore(tmp_path / "store")
    src = tmp_path / "guide.md"
    src.write_text("# Storage\nSQLite payload runtime.", encoding="utf-8")
    manifest = ingest_paths([src], store, "storage-api")
    monkeypatch.setattr(api_module, "STORE", store)
    client = TestClient(api_module.app)

    r = client.get(f"/api/corpora/{manifest.corpus_id}/storage")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "sqlite-payload"
    assert body["stored_blocks"] >= manifest.required_blocks
    assert body["policy"].startswith("payload storage only")
    assert client.get("/health").json()["version"] == __version__
