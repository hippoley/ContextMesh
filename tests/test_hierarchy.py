from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.reader import CorpusReader
from contextmesh.store import FileContextStore


def test_markdown_builds_addressable_hierarchy(tmp_path: Path):
    f = tmp_path / "policy.md"
    f.write_text("# Refunds\nRefunds are 30 days.\n\n## Exceptions\nLegacy enterprise contracts are excluded.\n")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([f], store, "corp", window_chars=200, overlap_chars=0)

    assert manifest.root_block_ids
    assert manifest.structural_block_ids
    reader = CorpusReader(store, "corp")
    exception_leaf = next(b for b in (reader.read(x) for x in manifest.block_ids) if "Legacy enterprise" in b.text)
    section = reader.parent(exception_leaf.id)
    assert section is not None
    assert section.title == "Exceptions"
    assert section.processable is False
    parent = reader.parent(section.id)
    assert parent is not None
    assert parent.title == "Refunds"


def test_neighbor_range_crosses_window_boundaries(tmp_path: Path):
    f = tmp_path / "doc.txt"
    f.write_text("A" * 120)
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([f], store, "corp", window_chars=50, overlap_chars=0)
    reader = CorpusReader(store, "corp")
    blocks = reader.range(manifest.block_ids[1], radius=1)
    assert [b.id for b in blocks] == manifest.block_ids[:3]
