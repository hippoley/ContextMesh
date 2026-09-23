from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.rlm_bridge import build_rlm_tool_bundle
from contextmesh.store import FileContextStore


def test_rlm_tool_bundle_exposes_full_coverage_tools(tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text("# A\nhello\n# B\nworld", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    ingest_paths([src], store, "c", window_chars=10, overlap_chars=0)
    bundle = build_rlm_tool_bundle(store, "c")
    tools = bundle.custom_tools()
    assert "cm_next_unvisited" in tools
    assert "cm_coverage" in tools
    first = tools["cm_next_unvisited"]["tool"]()
    assert first is not None
    tools["cm_read"]["tool"](first)
    assert tools["cm_coverage"]["tool"]()["visited"] == 1
