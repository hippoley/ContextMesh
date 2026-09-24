from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import ContextBlock
from .relations import block_matches_hint, extract_reference_hints
from .store import FileContextStore


@dataclass(frozen=True)
class NeighborWindow:
    previous: ContextBlock | None
    current: ContextBlock
    next: ContextBlock | None


class CorpusReader:
    """Addressable external-context reader.

    Search/ranking is intentionally navigation-only: every required block remains
    eligible and can still be traversed by next_unvisited().
    """

    def __init__(self, store: FileContextStore, corpus_id: str):
        self.store = store
        self.corpus_id = corpus_id
        self.manifest = store.get_manifest(corpus_id)

    @property
    def required_ids(self) -> list[str]:
        return self.manifest.coverage_ids()

    def read(self, block_id: str) -> ContextBlock:
        return self.store.get_block(self.corpus_id, block_id)

    def parent(self, block_id: str) -> ContextBlock | None:
        block = self.read(block_id)
        return self.read(block.parent_id) if block.parent_id else None

    def children(self, block_id: str) -> list[ContextBlock]:
        block = self.read(block_id)
        return [self.read(x) for x in block.children_ids]

    def neighbors(self, block_id: str) -> NeighborWindow:
        block = self.read(block_id)
        return NeighborWindow(
            previous=self.read(block.prev_id) if block.prev_id else None,
            current=block,
            next=self.read(block.next_id) if block.next_id else None,
        )

    def range(self, block_id: str, radius: int = 1) -> list[ContextBlock]:
        if radius < 0:
            raise ValueError("radius must be >= 0")
        center = self.read(block_id)
        out: list[ContextBlock] = [center]
        cursor = center
        left: list[ContextBlock] = []
        for _ in range(radius):
            if not cursor.prev_id:
                break
            cursor = self.read(cursor.prev_id)
            left.append(cursor)
        cursor = center
        right: list[ContextBlock] = []
        for _ in range(radius):
            if not cursor.next_id:
                break
            cursor = self.read(cursor.next_id)
            right.append(cursor)
        return list(reversed(left)) + out + right


    @staticmethod
    def _location_signature(block: ContextBlock) -> tuple | None:
        """Return a stable co-location key for blocks that represent the same source region.

        This is intentionally structural, not semantic retrieval: blocks sharing a page,
        slide, sheet, workbook render page, or overlapping timeline segment can be
        inspected together without changing coverage eligibility.
        """
        loc = block.source.locator
        for key in ("page", "slide", "sheet_name", "sheet", "workbook_page"):
            if loc.get(key) is not None:
                return (block.source.asset_id, key, str(loc.get(key)))
        start = loc.get("start_time") if loc.get("start_time") is not None else loc.get("time_start")
        end = loc.get("end_time") if loc.get("end_time") is not None else loc.get("time_end")
        if start is not None or end is not None:
            return (block.source.asset_id, "timeline", float(start or 0.0), float(end if end is not None else start or 0.0))
        return None

    def related(self, block_id: str, *, limit: int = 12) -> list[ContextBlock]:
        """Return structurally co-located blocks without changing the coverage set.

        Examples: PDF page text + rendered page image, PPT slide text + slide image,
        or multiple modalities covering the same timeline interval.
        """
        center = self.read(block_id)
        sig = self._location_signature(center)
        if sig is None:
            return []
        out: list[ContextBlock] = []
        for candidate_id in self.required_ids:
            if candidate_id == block_id:
                continue
            candidate = self.read(candidate_id)
            csig = self._location_signature(candidate)
            if csig is None:
                continue
            if sig[:2] != csig[:2]:
                continue
            if sig[1] == "timeline":
                _, _, a0, a1 = sig
                _, _, b0, b1 = csig
                if max(a0, b0) > min(a1, b1):
                    continue
            elif sig != csig:
                continue
            out.append(candidate)
            if len(out) >= limit:
                break
        return out

    def next_unvisited(self, visited: set[str], order: Iterable[str] | None = None) -> str | None:
        preferred = list(order or [])
        seen = set()
        for block_id in preferred + self.required_ids:
            if block_id in seen:
                continue
            seen.add(block_id)
            if block_id in self.required_ids and block_id not in visited:
                return block_id
        return None

    def references(self, block_id: str, *, limit: int = 12) -> list[ContextBlock]:
        """Resolve explicit in-document references such as page/slide/sheet pointers."""
        center = self.read(block_id)
        hints = extract_reference_hints(center.text)
        if not hints:
            return []
        out: list[ContextBlock] = []
        seen: set[str] = set()
        for candidate_id in self.required_ids:
            if candidate_id == block_id or candidate_id in seen:
                continue
            candidate = self.read(candidate_id)
            if candidate.source.asset_id != center.source.asset_id:
                continue
            if any(block_matches_hint(candidate, hint) for hint in hints):
                out.append(candidate); seen.add(candidate_id)
                if len(out) >= limit:
                    break
        return out

    def lexical_order(self, query: str) -> list[str]:
        """Indexed navigation/scheduling order. Coverage eligibility is unchanged."""
        required = list(self.required_ids)
        required_set = set(required)
        try:
            ranked = self.store.search_blocks(self.corpus_id, query, limit=min(max(len(required), 100), 5000))
            ordered = [block_id for block_id in ranked if block_id in required_set]
            seen = set(ordered)
            # FTS never filters coverage. Every required block is appended exactly once.
            ordered.extend(block_id for block_id in required if block_id not in seen)
            return ordered
        except Exception:
            # Portable fallback for damaged/unsupported indexes.
            terms = {t.lower().strip(".,?!:;()[]{}") for t in query.split() if len(t) > 2}
            scored: list[tuple[int, int, str]] = []
            for pos, block_id in enumerate(required):
                block = self.read(block_id)
                text = block.text.lower()
                score = sum(text.count(t) for t in terms if t)
                scored.append((-score, pos, block_id))
            scored.sort()
            return [block_id for _, _, block_id in scored]
