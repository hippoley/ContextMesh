from pathlib import Path

from contextmesh.judges import OpenAICompatibleJudge
from contextmesh.models import BlockKind, ContextBlock, Modality, SourceRef

# 1x1 transparent PNG
PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082')


def test_direct_image_becomes_vision_content(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(PNG)
    block = ContextBlock(
        id="b", corpus_id="c", modality=Modality.IMAGE, kind=BlockKind.IMAGE,
        text="caption", source=SourceRef(asset_id="a", path=str(img))
    )
    judge = OpenAICompatibleJudge("model", "http://localhost:1")
    parts = judge.build_block_content("q", "a", block)
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_video_falls_back_to_extracted_text(tmp_path: Path):
    video = tmp_path / "x.mp4"
    video.write_bytes(b"fake")
    block = ContextBlock(
        id="b", corpus_id="c", modality=Modality.VIDEO, kind=BlockKind.VIDEO,
        text="00:01 speaker says hello", source=SourceRef(asset_id="a", path=str(video))
    )
    judge = OpenAICompatibleJudge("model", "http://localhost:1")
    parts = judge.build_block_content("q", "a", block)
    assert len(parts) == 1
    assert "speaker says hello" in parts[0]["text"]
