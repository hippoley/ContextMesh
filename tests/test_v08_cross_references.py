from pathlib import Path

from contextmesh.models import BlockKind, ContextBlock, CorpusManifest, Modality, SourceRef
from contextmesh.reader import CorpusReader
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.judges import HeuristicJudge
from contextmesh.store import FileContextStore


def _put(store, cid, block_id, text, page):
    b = ContextBlock(
        id=block_id, corpus_id=cid, modality=Modality.TEXT, kind=BlockKind.CONTENT,
        text=text, source=SourceRef(asset_id="a", path="manual.pdf", locator={"page": page}),
    )
    store.put_block(b)
    return b


def test_explicit_page_reference_is_resolved(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    cid = "refs"
    _put(store, cid, "p1", "Policy applies subject to the exception on page 3.", 1)
    _put(store, cid, "p2", "Background only.", 2)
    _put(store, cid, "p3", "EXCEPTION: enterprise customers may proceed.", 3)
    store.put_manifest(CorpusManifest(
        corpus_id=cid, assets=["manual.pdf"], block_ids=["p1","p2","p3"], required_block_ids=["p1","p2","p3"],
        total_blocks=3, required_blocks=3, total_chars=100,
    ))
    reader = CorpusReader(store, cid)
    assert [x.id for x in reader.references("p1")] == ["p3"]


def test_contextual_block_includes_explicit_reference_target(tmp_path: Path):
    class NeighborJudge(HeuristicJudge):
        supports_neighbor_context = True

    store = FileContextStore(tmp_path / "store")
    cid = "refs2"
    _put(store, cid, "p1", "See page 3 for the controlling exception.", 1)
    _put(store, cid, "p2", "Background only.", 2)
    _put(store, cid, "p3", "NEEDLE-EXCEPTION-42", 3)
    store.put_manifest(CorpusManifest(
        corpus_id=cid, assets=["manual.pdf"], block_ids=["p1","p2","p3"], required_block_ids=["p1","p2","p3"],
        total_blocks=3, required_blocks=3, total_chars=100,
    ))
    ev = ProgressiveEvaluator(store, NeighborJudge(), neighbor_context_chars=200)
    contextual = ev._contextual_block(CorpusReader(store, cid), "p1")
    assert "NEEDLE-EXCEPTION-42" in contextual.text
    assert contextual.metadata["contextmesh_reference_block_ids"] == ["p3"]
