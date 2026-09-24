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

    @staticmethod
    def _locator_fields(block: ContextBlock) -> tuple[str, float | None, float | None]:
        loc = block.source.locator or {}
        for key in ("page", "slide", "sheet_name", "sheet", "workbook_page"):
            if loc.get(key) is not None:
                return f"{key}:{str(loc.get(key)).strip().lower()}", None, None
        start = loc.get("start_time") if loc.get("start_time") is not None else loc.get("time_start")
        end = loc.get("end_time") if loc.get("end_time") is not None else loc.get("time_end")
        if start is not None or end is not None:
            a = float(start or 0.0)
            b = float(end if end is not None else start or 0.0)
            return "timeline", min(a, b), max(a, b)
        return "", None, None

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
                    location_key TEXT NOT NULL DEFAULT '',
                    time_start REAL,
                    time_end REAL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (corpus_id, block_id)
                )
                """
            )
            # Online schema migration for catalogs created before v0.12.
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(blocks)").fetchall()}
            if "location_key" not in columns:
                conn.execute("ALTER TABLE blocks ADD COLUMN location_key TEXT NOT NULL DEFAULT ''")
            if "time_start" not in columns:
                conn.execute("ALTER TABLE blocks ADD COLUMN time_start REAL")
            if "time_end" not in columns:
                conn.execute("ALTER TABLE blocks ADD COLUMN time_end REAL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_corpus ON blocks(corpus_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_asset ON blocks(corpus_id, asset_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_location ON blocks(corpus_id, asset_id, location_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_timeline ON blocks(corpus_id, asset_id, time_start, time_end)")
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

    @classmethod
    def _row(cls, block: ContextBlock) -> tuple:
        location_key, time_start, time_end = cls._locator_fields(block)
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
            location_key,
            time_start,
            time_end,
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
                INSERT INTO blocks(corpus_id, block_id, asset_id, path, modality, kind, title, text, processable, locator_json, location_key, time_start, time_end, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(corpus_id, block_id) DO UPDATE SET
                    asset_id=excluded.asset_id,
                    path=excluded.path,
                    modality=excluded.modality,
                    kind=excluded.kind,
                    title=excluded.title,
                    text=excluded.text,
                    processable=excluded.processable,
                    locator_json=excluded.locator_json,
                    location_key=excluded.location_key,
                    time_start=excluded.time_start,
                    time_end=excluded.time_end,
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

    def related_ids(self, block: ContextBlock, *, limit: int = 12) -> list[str]:
        """Return structurally co-located IDs using indexed locator columns.

        This replaces O(corpus-size) payload scans for PDF pages, PPT slides, sheets
        and timeline overlap checks. It is structural lookup, not semantic retrieval.
        """
        location_key, time_start, time_end = self._locator_fields(block)
        with self._lock, self._connect() as conn:
            if location_key and location_key != "timeline":
                rows = conn.execute(
                    """
                    SELECT block_id FROM blocks
                    WHERE corpus_id=? AND asset_id=? AND location_key=? AND block_id<>?
                    ORDER BY block_id LIMIT ?
                    """,
                    (block.corpus_id, block.source.asset_id, location_key, block.id, limit),
                ).fetchall()
            elif location_key == "timeline" and time_start is not None and time_end is not None:
                rows = conn.execute(
                    """
                    SELECT block_id FROM blocks
                    WHERE corpus_id=? AND asset_id=? AND location_key='timeline' AND block_id<>?
                      AND COALESCE(time_start, 0) <= ? AND COALESCE(time_end, time_start, 0) >= ?
                    ORDER BY time_start, block_id LIMIT ?
                    """,
                    (block.corpus_id, block.source.asset_id, block.id, time_end, time_start, limit),
                ).fetchall()
            else:
                return []
        return [str(row[0]) for row in rows]

    def reference_ids(self, corpus_id: str, asset_id: str, hints: Iterable[Any], *, limit: int = 12) -> list[str]:
        keys: list[str] = []
        for hint in hints:
            kind = str(getattr(hint, "kind", ""))
            value = str(getattr(hint, "value", "")).strip().lower()
            if kind in {"page", "slide", "sheet_name", "sheet", "workbook_page"} and value:
                keys.append(f"{kind}:{value}")
                if kind == "sheet_name":
                    keys.append(f"sheet:{value}")
        keys = list(dict.fromkeys(keys))
        if not keys:
            return []
        out: list[str] = []
        with self._lock, self._connect() as conn:
            for start in range(0, len(keys), 200):
                chunk = keys[start:start + 200]
                marks = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""
                    SELECT block_id FROM blocks
                    WHERE corpus_id=? AND asset_id=? AND location_key IN ({marks})
                    ORDER BY block_id LIMIT ?
                    """,
                    [corpus_id, asset_id, *chunk, max(1, limit - len(out))],
                ).fetchall()
                out.extend(str(row[0]) for row in rows)
                if len(out) >= limit:
                    break
        return list(dict.fromkeys(out))[:limit]

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
