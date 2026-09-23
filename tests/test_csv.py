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
