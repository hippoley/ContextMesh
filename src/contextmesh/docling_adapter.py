from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import BlockKind, Modality


@dataclass
class ParsedItem:
    kind: BlockKind
    modality: Modality
    text: str
    title: str | None = None
    level: int = 1
    locator: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    items: list[ParsedItem]
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_with_docling(path: Path) -> ParsedDocument | None:
    """Convert a rich document into reading-order items using Docling.

    Returns None when Docling is not installed. The rest of ContextMesh remains
    usable for native text/CSV ingestion without the optional dependency.
    """
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
        from docling_core.types.doc import PictureItem, TableItem, TextItem  # type: ignore
    except Exception:
        return None

    result = DocumentConverter().convert(str(path))
    doc = result.document
    items: list[ParsedItem] = []

    for element, level in doc.iterate_items(traverse_pictures=True):
        locator: dict[str, Any] = {"docling_ref": getattr(element, "self_ref", None)}
        prov = getattr(element, "prov", None) or []
        if prov:
            first = prov[0]
            page_no = getattr(first, "page_no", None)
            if page_no is not None:
                locator["page"] = page_no
            bbox = getattr(first, "bbox", None)
            if bbox is not None:
                for name in ("l", "t", "r", "b", "left", "top", "right", "bottom"):
                    value = getattr(bbox, name, None)
                    if value is not None:
                        locator.setdefault("bbox", {})[name] = value
            charspan = getattr(first, "charspan", None)
            if charspan is not None:
                try:
                    locator["charspan"] = list(charspan)
                except Exception:
                    locator["charspan"] = str(charspan)

        # Preserve format-specific addressing when Docling exposes it. These are
        # intentionally introspective so ContextMesh keeps working across Docling
        # versions without hard-coding one internal document schema.
        for key in ("slide_no", "slide", "sheet_name", "sheet", "start_time", "end_time", "timestamp", "time_start", "time_end"):
            value = getattr(element, key, None)
            if value is not None:
                locator[key] = value
        meta_obj = getattr(element, "meta", None)
        if meta_obj is not None:
            for key in ("slide_no", "sheet_name", "start_time", "end_time", "timestamp"):
                value = getattr(meta_obj, key, None)
                if value is not None:
                    locator.setdefault(key, value)

        if isinstance(element, TableItem):
            try:
                text = element.export_to_markdown(doc=doc)
            except TypeError:
                try:
                    text = element.export_to_markdown()
                except Exception:
                    text = str(element)
            except Exception:
                text = str(element)
            items.append(
                ParsedItem(
                    kind=BlockKind.TABLE,
                    modality=Modality.TABLE,
                    text=text,
                    level=max(1, int(level)),
                    locator=locator,
                    metadata={"docling_type": type(element).__name__},
                )
            )
            continue

        if isinstance(element, PictureItem):
            caption = ""
            try:
                caption = element.caption_text(doc)
            except Exception:
                pass
            description = None
            meta = getattr(element, "meta", None)
            if meta is not None and getattr(meta, "description", None) is not None:
                description = getattr(meta.description, "text", None)
            text = "\n".join(x for x in [caption, description] if x)
            items.append(
                ParsedItem(
                    kind=BlockKind.IMAGE,
                    modality=Modality.IMAGE,
                    text=text,
                    level=max(1, int(level)),
                    locator=locator,
                    metadata={"docling_type": type(element).__name__},
                )
            )
            continue

        if isinstance(element, TextItem):
            text = getattr(element, "text", "") or ""
            label = str(getattr(element, "label", "")).lower()
            is_heading = "section_header" in label or type(element).__name__.lower().endswith("headeritem")
            items.append(
                ParsedItem(
                    kind=BlockKind.SECTION if is_heading else BlockKind.CONTENT,
                    modality=Modality.TEXT,
                    text=text,
                    title=text if is_heading else None,
                    level=max(1, int(level)),
                    locator=locator,
                    metadata={"docling_type": type(element).__name__, "label": str(getattr(element, "label", ""))},
                )
            )

    return ParsedDocument(items=items, metadata={"parser": "docling", "docling_name": getattr(doc, "name", path.stem)})
