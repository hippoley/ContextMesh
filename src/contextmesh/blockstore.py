from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Iterable, Protocol

from .models import ContextBlock


class BlockPayloadStore(Protocol):
    backend: str

    def put_many(self, blocks: Iterable[ContextBlock]) -> int: ...
    def get(self, corpus_id: str, block_id: str) -> ContextBlock: ...
    def get_many(self, corpus_id: str, block_ids: Iterable[str]) -> list[ContextBlock]: ...
    def existing_ids(self, corpus_id: str, block_ids: Iterable[str]) -> set[str]: ...
    def delete_corpus(self, corpus_id: str) -> None: ...
    def count(self, corpus_id: str) -> int: ...


class JsonBlockPayloadStore:
    """Legacy portable JSON-per-block payload store.

    This backend remains available for exports, debugging and backwards
    compatibility. It is not the recommended runtime backend for very large corpora
    because millions of small files stress directory metadata and inode operations.
    """

    backend = "json-files"

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _path(self, corpus_id: str, block_id: str) -> Path:
        return self.root / corpus_id / "blocks" / f"{block_id}.json"

    def put_many(self, blocks: Iterable[ContextBlock]) -> int:
        count = 0
        with self._lock:
            for block in blocks:
                self._atomic_write(self._path(block.corpus_id, block.id), block.model_dump_json())
                count += 1
        return count

    def get(self, corpus_id: str, block_id: str) -> ContextBlock:
        p = self._path(corpus_id, block_id)
        return ContextBlock.model_validate_json(p.read_text(encoding="utf-8"))

    def get_many(self, corpus_id: str, block_ids: Iterable[str]) -> list[ContextBlock]:
        out: list[ContextBlock] = []
        for block_id in block_ids:
            try:
                out.append(self.get(corpus_id, block_id))
            except FileNotFoundError:
                continue
        return out

    def existing_ids(self, corpus_id: str, block_ids: Iterable[str]) -> set[str]:
        return {block_id for block_id in block_ids if self._path(corpus_id, block_id).is_file()}

    def delete_corpus(self, corpus_id: str) -> None:
        # The owning FileContextStore removes the corpus directory itself.
        return None

    def count(self, corpus_id: str) -> int:
        d = self.root / corpus_id / "blocks"
        if not d.exists():
            return 0
        return sum(1 for p in d.glob("*.json") if p.is_file())


class SQLiteBlockPayloadStore:
    """Single-node runtime payload store for hundreds of thousands/millions of blocks.

    ContextBlock JSON payloads are kept in one WAL-mode SQLite database. The manifest
    remains the coverage authority; this database is only the addressable block body
    store. It deliberately does not perform ranking/search (the catalog owns that).
    """

    backend = "sqlite-payload"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS block_payloads (
                    corpus_id TEXT NOT NULL,
                    block_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (corpus_id, block_id)
                ) WITHOUT ROWID
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_block_payloads_corpus ON block_payloads(corpus_id)"
            )

    def put_many(self, blocks: Iterable[ContextBlock]) -> int:
        items = list(blocks)
        if not items:
            return 0
        now = time.time()
        rows = [(b.corpus_id, b.id, b.model_dump_json(), now) for b in items]
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO block_payloads(corpus_id, block_id, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(corpus_id, block_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
        return len(items)

    def get(self, corpus_id: str, block_id: str) -> ContextBlock:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM block_payloads WHERE corpus_id=? AND block_id=?",
                (corpus_id, block_id),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"block not found in sqlite payload store: {corpus_id}/{block_id}")
        return ContextBlock.model_validate_json(str(row[0]))

    def get_many(self, corpus_id: str, block_ids: Iterable[str]) -> list[ContextBlock]:
        ids = list(dict.fromkeys(str(x) for x in block_ids))
        if not ids:
            return []
        payloads: dict[str, str] = {}
        with self._lock, self._connect() as conn:
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                marks = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT block_id, payload_json FROM block_payloads WHERE corpus_id=? AND block_id IN ({marks})",
                    [corpus_id, *chunk],
                ).fetchall()
                payloads.update({str(row[0]): str(row[1]) for row in rows})
        return [ContextBlock.model_validate_json(payloads[x]) for x in ids if x in payloads]

    def existing_ids(self, corpus_id: str, block_ids: Iterable[str]) -> set[str]:
        ids = list(dict.fromkeys(str(x) for x in block_ids))
        if not ids:
            return set()
        found: set[str] = set()
        with self._lock, self._connect() as conn:
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                marks = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT block_id FROM block_payloads WHERE corpus_id=? AND block_id IN ({marks})",
                    [corpus_id, *chunk],
                ).fetchall()
                found.update(str(row[0]) for row in rows)
        return found

    def delete_corpus(self, corpus_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM block_payloads WHERE corpus_id=?", (corpus_id,))

    def count(self, corpus_id: str) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM block_payloads WHERE corpus_id=?", (corpus_id,)
            ).fetchone()
        return int(row[0] if row else 0)

    def stats(self, corpus_id: str) -> dict:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS blocks, COALESCE(SUM(LENGTH(payload_json)), 0) AS json_chars
                FROM block_payloads WHERE corpus_id=?
                """,
                (corpus_id,),
            ).fetchone()
        return {
            "backend": self.backend,
            "stored_blocks": int(row["blocks"] or 0),
            "payload_json_chars": int(row["json_chars"] or 0),
            "database_path": str(self.path),
        }
