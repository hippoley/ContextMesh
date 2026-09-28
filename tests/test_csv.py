from pathlib import Path

from contextmesh.ingest import ingest_paths
from contextmesh.models import Modality
from contextmesh.store import FileContextStore


def test_csv_is_partitioned_as_table_blocks_with_schema(tmp_path: Path):
    f = tmp_path / "sales.csv"
    f.write_text("region,revenue\nEU,10\nUS,20\nAPAC,30\n")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([f], store, "corp")
    block = store.get_block("corp", manifest.block_ids[0])
    assert block.modality == Modality.TABLE
    assert block.metadata["columns"] == ["region", "revenue"]
    assert "EU\t10" in block.text
    assert block.source.locator["row_start"] == 2



def test_csv_optional_table_bound_preserves_all_text(tmp_path: Path):
    f = tmp_path / "wide.csv"
    rows = ["region,notes"]
    rows.extend(f"r{i}," + ("x" * 90) for i in range(20))
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")

    default_store = FileContextStore(tmp_path / "default-store")
    default_manifest = ingest_paths([f], default_store, "csv-default")
    default_text = "".join(
        default_store.get_block(default_manifest.corpus_id, block_id).text
        for block_id in default_manifest.required_block_ids
    )

    bounded_store = FileContextStore(tmp_path / "bounded-store")
    bounded_manifest = ingest_paths(
        [f],
        bounded_store,
        "csv-bounded",
        max_table_block_chars=220,
    )
    bounded_blocks = [
        bounded_store.get_block(bounded_manifest.corpus_id, block_id)
        for block_id in bounded_manifest.required_block_ids
    ]

    assert len(bounded_blocks) > 1
    assert all(block.modality == Modality.TABLE for block in bounded_blocks)
    assert all(len(block.text) <= 220 for block in bounded_blocks)
    assert "".join(block.text for block in bounded_blocks) == default_text
    assert all(
        block.metadata.get("bounded_from_block_id")
        for block in bounded_blocks
    )
