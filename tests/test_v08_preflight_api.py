from pathlib import Path
from fastapi.testclient import TestClient

import contextmesh.api as api
from contextmesh.models import BlockKind, ContextBlock, CorpusManifest, Modality, SourceRef


def test_preflight_endpoint_reports_missing_vision(tmp_path: Path, monkeypatch):
    from PIL import Image
    from contextmesh.store import FileContextStore

    store = FileContextStore(tmp_path / "store")
    monkeypatch.setattr(api, "STORE", store)
    img = tmp_path / "scan.png"
    Image.new("RGB", (8, 8), "white").save(img)
    block = ContextBlock(
        id="v", corpus_id="c", modality=Modality.IMAGE, kind=BlockKind.IMAGE, text="",
        source=SourceRef(asset_id="a", path=str(img), locator={"page": 1}),
        required_capabilities=["vision"], metadata={"media_path": str(img), "media_mime": "image/png"},
    )
    store.put_block(block)
    store.put_manifest(CorpusManifest(
        corpus_id="c", assets=[str(img)], block_ids=["v"], required_block_ids=["v"],
        total_blocks=1, required_blocks=1, total_chars=0, required_capabilities=["vision"],
    ))
    client = TestClient(api.app)
    r = client.post('/api/preflight', json={'corpus_id':'c'})
    assert r.status_code == 200
    body = r.json()
    assert body['ready'] is False
    assert body['unsupported_blocks'] == 1
    assert 'vision' in body['unsupported_capabilities']
