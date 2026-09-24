from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from .models import ContextBlock, Evidence, EvidenceAtom, EvidenceKind

_DATE_PATTERNS = [
    re.compile(r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b"),
    re.compile(r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])\b"),
]
_NUMBER_RE = re.compile(
    r"(?<!\w)(?P<currency>[$€£¥￥])?\s*(?P<number>-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>%|percent|bps|ms|s|sec|seconds?|minutes?|mins?|hours?|days?|MB|GB|TB|KB|USD|EUR|GBP|CNY|RMB)?",
    re.IGNORECASE,
)
_EXCEPTION_RE = re.compile(r"\b(?:except(?:ion)?|unless|excluding|other than|except for)\b|除非|例外|除外|不包括", re.IGNORECASE)
_CONTRADICTION_RE = re.compile(r"\b(?:however|but|contradict(?:s|ed|ion)?|instead|whereas|not|no longer|never)\b|但是|然而|相反|矛盾|不得|不能|并非", re.IGNORECASE)
_REQUIREMENT_RE = re.compile(r"\b(?:must|shall|required|requirement|need to|has to|may not|must not)\b|必须|应当|需要|不得|禁止", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？;；])\s+|\n+", text or "")
    return [x.strip() for x in parts if x and x.strip()]


def _clip(text: str, limit: int = 320) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _dedupe(atoms: Iterable[EvidenceAtom]) -> list[EvidenceAtom]:
    out: list[EvidenceAtom] = []
    seen: set[tuple] = set()
    for atom in atoms:
        key = (
            atom.kind.value,
            atom.text.lower().strip(),
            (atom.normalized_value or "").lower().strip(),
            (atom.unit or "").lower().strip(),
            atom.date or "",
            atom.polarity,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(atom)
    return out


def extract_evidence_atoms(block: ContextBlock, note: str = "", *, max_atoms: int = 24) -> list[EvidenceAtom]:
    """Derive typed, source-linked evidence without replacing the raw note.

    This deterministic pass is intentionally conservative. Provider adapters may add
    richer atoms later, but every atom here can be traced back to the source block.
    """
    source_text = block.text or ""
    joined = "\n".join(x for x in [note, source_text] if x)
    atoms: list[EvidenceAtom] = []

    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(joined):
            atoms.append(EvidenceAtom(
                kind=EvidenceKind.DATE,
                text=_clip(m.group(0)),
                date=m.group(0),
                normalized_value=m.group(0),
                confidence=0.99,
            ))

    for m in _NUMBER_RE.finditer(joined):
        token = m.group(0).strip()
        number = m.group("number")
        if not token or not number:
            continue
        # Ignore isolated small integers that are overwhelmingly likely to be list/page noise.
        unit = (m.group("unit") or "").strip() or None
        currency = (m.group("currency") or "").strip()
        if not unit and not currency and len(number.replace(",", "").replace(".", "")) < 2:
            continue
        atoms.append(EvidenceAtom(
            kind=EvidenceKind.NUMBER,
            text=_clip(token),
            normalized_value=number.replace(",", ""),
            unit=(currency + (unit or "")) or None,
            confidence=0.96,
        ))

    for sentence in _sentences(joined):
        kind: EvidenceKind | None = None
        polarity = "affirm"
        if _EXCEPTION_RE.search(sentence):
            kind = EvidenceKind.EXCEPTION
        elif _REQUIREMENT_RE.search(sentence):
            kind = EvidenceKind.REQUIREMENT
            if re.search(r"must not|may not|不得|禁止", sentence, re.IGNORECASE):
                polarity = "deny"
        elif _CONTRADICTION_RE.search(sentence):
            kind = EvidenceKind.CONTRADICTION
            polarity = "deny" if re.search(r"\b(?:not|never|no longer)\b|不得|不能|并非", sentence, re.IGNORECASE) else "contrast"
        if kind:
            atoms.append(EvidenceAtom(kind=kind, text=_clip(sentence), polarity=polarity, confidence=0.88))

    # Always retain one compact claim atom for a relevant evidence record. This keeps
    # free-form provider notes auditable while structured types carry critical details.
    claim_source = note.strip() or (_sentences(source_text)[0] if _sentences(source_text) else "")
    if claim_source:
        atoms.append(EvidenceAtom(kind=EvidenceKind.CLAIM, text=_clip(claim_source), confidence=0.8))

    return _dedupe(atoms)[:max_atoms]


def evidence_kind_counts(evidence: Iterable[Evidence]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in evidence:
        for atom in item.atoms:
            counter[atom.kind.value] += 1
    return dict(sorted(counter.items()))


def render_typed_evidence(evidence: Iterable[Evidence], *, max_atoms: int = 256, max_chars: int = 32_000) -> str:
    """Render typed evidence into bounded, source-addressed model state."""
    lines: list[str] = []
    count = 0
    for item in evidence:
        for atom in item.atoms:
            if count >= max_atoms:
                break
            extras: list[str] = []
            if atom.normalized_value:
                extras.append(f"value={atom.normalized_value}")
            if atom.unit:
                extras.append(f"unit={atom.unit}")
            if atom.date:
                extras.append(f"date={atom.date}")
            if atom.polarity != "affirm":
                extras.append(f"polarity={atom.polarity}")
            suffix = " " + " ".join(extras) if extras else ""
            line = f"[{atom.kind.value.upper()} block={item.block_id} source={item.source.path}] {atom.text}{suffix}"
            current_chars = sum(len(x) + 1 for x in lines)
            if lines and current_chars + len(line) + 1 > max_chars:
                return "\n".join(lines)
            lines.append(line)
            count += 1
        if count >= max_atoms:
            break
    return "\n".join(lines)
