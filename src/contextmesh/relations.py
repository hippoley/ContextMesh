from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ContextBlock


@dataclass(frozen=True)
class ReferenceHint:
    kind: str
    value: str


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("page", re.compile(r"(?:page|p\.?|第)\s*(\d+)\s*(?:页)?", re.IGNORECASE)),
    ("slide", re.compile(r"(?:slide|幻灯片)\s*(\d+)", re.IGNORECASE)),
    ("sheet_name", re.compile(r"(?:sheet|worksheet|工作表)\s*[\"'“”]?([\w\- .\u4e00-\u9fff]{1,80})", re.IGNORECASE)),
]


def extract_reference_hints(text: str) -> list[ReferenceHint]:
    """Extract conservative explicit source-location references from block text.

    This intentionally avoids semantic retrieval. It only follows references that the
    source itself spells out, such as "see page 12" or "Sheet Revenue".
    """
    hints: list[ReferenceHint] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text or ""):
            value = match.group(1).strip().rstrip(".,;:)")
            key = (kind, value.lower())
            if key not in seen:
                hints.append(ReferenceHint(kind, value))
                seen.add(key)
    return hints


def block_matches_hint(block: ContextBlock, hint: ReferenceHint) -> bool:
    loc = block.source.locator
    if hint.kind in {"page", "slide"}:
        value = loc.get(hint.kind)
        if value is None and hint.kind == "slide":
            value = loc.get("page") if block.source.path.lower().endswith((".ppt", ".pptx")) else None
        try:
            return int(value) == int(hint.value)
        except Exception:
            return False
    if hint.kind == "sheet_name":
        value = loc.get("sheet_name") or loc.get("sheet")
        return value is not None and str(value).strip().lower() == hint.value.strip().lower()
    return False
