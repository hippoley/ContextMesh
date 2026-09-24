from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .models import ContextBlock

_TERM_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class SQLiteContextCatalog:
    """Portable metadata + FTS catalog for large corpora.

    The catalog is an acceleration/indexing layer only. It may rank navigation and
    execution order, but it never changes the manifest coverage set.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._fts_enabled = True
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS blocks (
                    corpus_id TEXT NOT NULL,
                    block_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    processable INTEGER NOT NULL DEFAULT 1,
                    locator_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (corpus_id, block_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_corpus ON blocks(corpus_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_asset ON blocks(corpus_id, asset_id)")
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5(
                        corpus_id UNINDEXED,
                        block_id UNINDEXED,
                        title,
                        text,
                        path
                    )
                    """
                )
            except sqlite3.OperationalError:
                self._fts_enabled = False

    @staticmethod
    def _row(block: ContextBlock) -> tuple:
        return (
            block.corpus_id,
            block.id,
            block.source.asset_id,
            block.source.path,
            block.modality.value,
            block.kind.value,
            block.title or "",
            block.text or "",
            1 if block.processable else 0,
            json.dumps(block.source.locator, ensure_ascii=False, sort_keys=True),
            time.time(),
        )

    def upsert(self, block: ContextBlock) -> None:
        self.upsert_many([block])

    def upsert_many(self, blocks: Iterable[ContextBlock]) -> int:
        items = list(blocks)
        if not items:
            return 0
        rows = [self._row(block) for block in items]
        with self._lock, self._connect() as conn:
            existing: set[tuple[str, str]] = set()
            # Avoid an expensive FTS DELETE for the overwhelmingly common fresh-ingest case.
            # SQLite has a bounded parameter count, so probe existing IDs in small groups.
            by_corpus: dict[str, list[str]] = {}
            for block in items:
                by_corpus.setdefault(block.corpus_id, []).append(block.id)
            for corpus_id, ids in by_corpus.items():
                for start in range(0, len(ids), 500):
                    chunk = ids[start:start + 500]
                    marks = ",".join("?" for _ in chunk)
                    query = f"SELECT block_id FROM blocks WHERE corpus_id=? AND block_id IN ({marks})"
                    for row in conn.execute(query, [corpus_id, *chunk]).fetchall():
                        existing.add((corpus_id, str(row[0])))
            conn.executemany(
                """
                INSERT INTO blocks(corpus_id, block_id, asset_id, path, modality, kind, title, text, processable, locator_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(corpus_id, block_id) DO UPDATE SET
                    asset_id=excluded.asset_id,
                    path=excluded.path,
                    modality=excluded.modality,
                    kind=excluded.kind,
                    title=excluded.title,
                    text=excluded.text,
                    processable=excluded.processable,
                    locator_json=excluded.locator_json,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
            if self._fts_enabled:
                if existing:
                    conn.executemany(
                        "DELETE FROM blocks_fts WHERE corpus_id=? AND block_id=?",
                        list(existing),
                    )
                conn.executemany(
                    "INSERT INTO blocks_fts(corpus_id, block_id, title, text, path) VALUES (?, ?, ?, ?, ?)",
                    [(block.corpus_id, block.id, block.title or "", block.text or "", block.source.path) for block in items],
                )
        return len(items)

    def delete_corpus(self, corpus_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM blocks WHERE corpus_id=?", (corpus_id,))
            if self._fts_enabled:
                conn.execute("DELETE FROM blocks_fts WHERE corpus_id=?", (corpus_id,))

    @staticmethod
    def _match_query(query: str) -> str:
        terms = [x for x in _TERM_RE.findall(query or "") if len(x) > 1]
        # Prefix terms improve interactive Explorer search while still keeping the
        # resulting ranking as scheduling/navigation only.
        return " OR ".join(f'"{x.replace(chr(34), "")}"*' for x in terms[:24])

    def search(self, corpus_id: str, query: str, *, limit: int = 100, processable_only: bool = True) -> list[str]:
        limit = max(1, min(int(limit), 5000))
        match = self._match_query(query)
        if not match:
            return []
        with self._lock, self._connect() as conn:
            if self._fts_enabled:
                try:
                    rows = conn.execute(
                        """
                        SELECT f.block_id
                        FROM blocks_fts AS f
                        JOIN blocks AS b ON b.corpus_id=f.corpus_id AND b.block_id=f.block_id
                        WHERE f.corpus_id=? AND blocks_fts MATCH ? AND (?=0 OR b.processable=1)
                        ORDER BY bm25(blocks_fts), b.updated_at DESC
                        LIMIT ?
                        """,
                        (corpus_id, match, 1 if processable_only else 0, limit),
                    ).fetchall()
                    return [str(r[0]) for r in rows]
                except sqlite3.OperationalError:
                    pass
            # Portable fallback when SQLite was built without FTS5.
            terms = [x.lower() for x in _TERM_RE.findall(query) if len(x) > 1][:24]
            rows = conn.execute(
                "SELECT block_id, title, text, path FROM blocks WHERE corpus_id=? AND (?=0 OR processable=1)",
                (corpus_id, 1 if processable_only else 0),
            ).fetchall()
            scored: list[tuple[int, str]] = []
            for row in rows:
                hay = " ".join([row[1] or "", row[2] or "", row[3] or ""]).lower()
                score = sum(hay.count(t) for t in terms)
                if score:
                    scored.append((-score, str(row[0])))
            scored.sort()
            return [block_id for _, block_id in scored[:limit]]

    def count(self, corpus_id: str) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM blocks WHERE corpus_id=?", (corpus_id,)).fetchone()
            return int(row[0] if row else 0)

    def stats(self, corpus_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS blocks,
                       SUM(CASE WHEN processable=1 THEN 1 ELSE 0 END) AS processable,
                       COALESCE(SUM(LENGTH(text)), 0) AS text_chars,
                       COUNT(DISTINCT asset_id) AS assets
                FROM blocks WHERE corpus_id=?
                """,
                (corpus_id,),
            ).fetchone()
            modalities = {
                str(r[0]): int(r[1])
                for r in conn.execute(
                    "SELECT modality, COUNT(*) FROM blocks WHERE corpus_id=? GROUP BY modality ORDER BY modality",
                    (corpus_id,),
                ).fetchall()
            }
        return {
            "backend": "sqlite-fts5" if self._fts_enabled else "sqlite-lexical",
            "fts_enabled": self._fts_enabled,
            "indexed_blocks": int(row["blocks"] or 0),
            "processable_blocks": int(row["processable"] or 0),
            "indexed_assets": int(row["assets"] or 0),
            "indexed_text_chars": int(row["text_chars"] or 0),
            "modalities": modalities,
            "policy": "ranking/scheduling only; never coverage eligibility",
        }
