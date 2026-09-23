from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .reader import CorpusReader


@dataclass
class ReaderSession:
    """Small stateful tool surface intended for RLM/CodeAct-style agents.

    The session never hides unvisited required blocks. Search only returns a
    preferred order; `next_unvisited` remains authoritative for coverage.
    """

    reader: CorpusReader
    visited: set[str] = field(default_factory=set)

    def manifest(self) -> dict[str, Any]:
        m = self.reader.manifest
        return {
            "corpus_id": m.corpus_id,
            "assets": m.assets,
            "required_blocks": len(self.reader.required_ids),
            "root_block_ids": m.root_block_ids,
            "warnings": m.ingest_warnings,
        }

    def read(self, block_id: str) -> dict[str, Any]:
        block = self.reader.read(block_id)
        if block.processable and block_id in self.reader.required_ids:
            self.visited.add(block_id)
        return block.model_dump()

    def parent(self, block_id: str) -> dict[str, Any] | None:
        block = self.reader.parent(block_id)
        return None if block is None else block.model_dump()

    def children(self, block_id: str) -> list[dict[str, Any]]:
        return [b.model_dump() for b in self.reader.children(block_id)]

    def neighbors(self, block_id: str) -> dict[str, Any]:
        w = self.reader.neighbors(block_id)
        return {
            "previous": None if w.previous is None else w.previous.model_dump(),
            "current": w.current.model_dump(),
            "next": None if w.next is None else w.next.model_dump(),
        }

    def read_range(self, block_id: str, radius: int = 1) -> list[dict[str, Any]]:
        blocks = self.reader.range(block_id, radius=radius)
        for block in blocks:
            if block.processable and block.id in self.reader.required_ids:
                self.visited.add(block.id)
        return [b.model_dump() for b in blocks]

    def search(self, query: str, limit: int = 20) -> list[str]:
        return self.reader.lexical_order(query)[:limit]

    def next_unvisited(self, preferred_order: list[str] | None = None) -> str | None:
        return self.reader.next_unvisited(self.visited, preferred_order)

    def coverage(self) -> dict[str, Any]:
        required = set(self.reader.required_ids)
        done = required & self.visited
        missing = required - self.visited
        return {
            "visited": len(done),
            "required": len(required),
            "coverage": 1.0 if not required else len(done) / len(required),
            "complete": required.issubset(self.visited),
            "remaining": len(missing),
        }
