from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from .models import ExplorerGroup
from .reader import CorpusReader
from .store import FileContextStore


def _group_descriptor(path: str, locator: dict) -> tuple[str, str, str]:
    ext = Path(path).suffix.lower()
    # Prefer explicit format-specific locators when present.
    slide = locator.get("slide") or locator.get("slide_no")
    if slide is not None:
        return (f"slide:{slide}", f"Slide {slide}", "slide")
    sheet = locator.get("sheet_name") or locator.get("sheet")
    if sheet is not None:
        return (f"sheet:{sheet}", f"Sheet {sheet}", "sheet")
    t0 = locator.get("start_time") if locator.get("start_time") is not None else locator.get("time_start")
    t1 = locator.get("end_time") if locator.get("end_time") is not None else locator.get("time_end")
    ts = locator.get("timestamp")
    if t0 is not None or t1 is not None or ts is not None:
        label = f"{t0 if t0 is not None else ts} → {t1 if t1 is not None else ''}".strip(" →")
        return (f"time:{label}", label or "Timeline segment", "timeline")
    page = locator.get("page")
    if page is not None:
        kind = "slide" if ext in {".ppt", ".pptx"} else "page"
        label = f"Slide {page}" if kind == "slide" else f"Page {page}"
        return (f"{kind}:{page}", label, kind)
    row_start = locator.get("row_start")
    row_end = locator.get("row_end")
    if row_start is not None:
        return (f"rows:{row_start}:{row_end}", f"Rows {row_start}–{row_end}", "rows")
    section = locator.get("section")
    if section:
        return (f"section:{section}", str(section), "section")
    return ("document", "Document", "document")


def build_explorer_groups(store: FileContextStore, corpus_id: str) -> list[ExplorerGroup]:
    reader = CorpusReader(store, corpus_id)
    groups: OrderedDict[tuple[str, str], ExplorerGroup] = OrderedDict()
    for block_id in reader.required_ids:
        block = reader.read(block_id)
        gkey, label, kind = _group_descriptor(block.source.path, block.source.locator)
        key = (block.source.path, gkey)
        if key not in groups:
            groups[key] = ExplorerGroup(
                key=f"{Path(block.source.path).name}:{gkey}",
                label=label,
                kind=kind,
                asset_path=block.source.path,
            )
        group = groups[key]
        group.block_ids.append(block.id)
        group.required_blocks += 1
        group.total_chars += len(block.text)
    return list(groups.values())
