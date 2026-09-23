from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.judges import HeuristicJudge, OpenAICompatibleJudge
from contextmesh.models import BlockKind, ContextBlock, CorpusManifest, Modality, SourceRef
from contextmesh.reader import CorpusReader
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.store import FileContextStore


def _manual_page_pair(store: FileContextStore, tmp_path: Path):
    from PIL import Image
    img = tmp_path / "page1.png"
    Image.new("RGB", (16, 16), "white").save(img)
    cid = "corp_pair"
    text = ContextBlock(
        id="t1", corpus_id=cid, modality=Modality.TEXT, kind=BlockKind.CONTENT,
        text="The exception code is NEEDLE-42.",
        source=SourceRef(asset_id="a1", path="report.pdf", locator={"page": 1, "channel": "text"}),
    )
    visual = ContextBlock(
        id="v1", corpus_id=cid, modality=Modality.IMAGE, kind=BlockKind.IMAGE, text="",
        source=SourceRef(asset_id="a1", path="report.pdf", locator={"page": 1, "channel": "visual"}),
        required_capabilities=["vision"], metadata={"media_path": str(img), "media_mime": "image/png"},
    )
    store.put_block(text); store.put_block(visual)
    store.put_manifest(CorpusManifest(
        corpus_id=cid, assets=["report.pdf"], block_ids=["t1", "v1"], required_block_ids=["t1", "v1"],
        total_blocks=2, required_blocks=2, total_chars=len(text.text), required_capabilities=["vision"],
    ))
    return cid


def test_reader_returns_colocated_page_modalities(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    cid = _manual_page_pair(store, tmp_path)
    reader = CorpusReader(store, cid)
    assert [b.id for b in reader.related("t1")] == ["v1"]
    assert [b.id for b in reader.related("v1")] == ["t1"]


def test_contextual_text_block_attaches_colocated_visual_path(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    cid = _manual_page_pair(store, tmp_path)
    judge = OpenAICompatibleJudge("m", "http://example.invalid/v1", capabilities=["text", "vision"])
    ev = ProgressiveEvaluator(store, judge)
    block = ev._contextual_block(CorpusReader(store, cid), "t1")
    assert block.metadata["contextmesh_related_block_ids"] == ["v1"]
    assert len(block.metadata["contextmesh_related_media_paths"]) == 1


def test_preflight_blocks_unsupported_route_before_any_inspection(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    cid = _manual_page_pair(store, tmp_path)
    result = ProgressiveEvaluator(store, HeuristicJudge()).evaluate(cid, "needle", "answer")
    assert result.score is None
    assert result.complete is False
    assert result.visited_blocks == 0
    assert result.failed_blocks == 1
    assert "blocked before execution" in result.rationale.lower()


def test_image_caption_can_fall_back_to_text_capability(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    cid = "caption"
    block = ContextBlock(
        id="i", corpus_id=cid, modality=Modality.IMAGE, kind=BlockKind.IMAGE,
        text="OCR/caption says NEEDLE-99", source=SourceRef(asset_id="a", path="x.pdf", locator={"page": 2}),
        required_capabilities=["vision"],
    )
    store.put_block(block)
    store.put_manifest(CorpusManifest(corpus_id=cid, assets=["x.pdf"], block_ids=["i"], required_block_ids=["i"], total_blocks=1, required_blocks=1, total_chars=len(block.text)))
    judge = OpenAICompatibleJudge("m", "http://example.invalid/v1", capabilities=["text"])
    assert judge.can_inspect(block) is True
