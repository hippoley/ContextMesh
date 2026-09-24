from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(slots=True)
class QueueJob:
    id: str
    kind: str
    logical_job_id: str
    payload: dict[str, Any]
    status: str
    priority: int
    attempts: int
    max_attempts: int
    available_at: float
    leased_by: str | None
    lease_expires_at: float | None
    cancel_requested: bool
    last_error: str | None
    created_at: float
    updated_at: float


class SQLiteJobQueue:
    """Durable single-host job queue backed by SQLite WAL.

    Multiple worker processes on the same host can lease jobs atomically. A
    crashed worker's lease expires and the job becomes eligible for another
    worker. The interface is deliberately narrow so Redis/NATS backends can
    implement the same contract later.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS queue_jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    logical_job_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    available_at REAL NOT NULL,
                    leased_by TEXT,
                    lease_expires_at REAL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_queue_claim
                    ON queue_jobs(status, available_at, priority, created_at);
                CREATE INDEX IF NOT EXISTS idx_queue_logical
                    ON queue_jobs(logical_job_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_queue_lease
                    ON queue_jobs(status, lease_expires_at);

                CREATE TABLE IF NOT EXISTS worker_heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    pid INTEGER,
                    hostname TEXT,
                    last_seen REAL NOT NULL,
                    active_job_id TEXT
                );
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> QueueJob | None:
        if row is None:
            return None
        return QueueJob(
            id=row["id"], kind=row["kind"], logical_job_id=row["logical_job_id"],
            payload=json.loads(row["payload_json"]), status=row["status"],
            priority=int(row["priority"]), attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]), available_at=float(row["available_at"]),
            leased_by=row["leased_by"], lease_expires_at=row["lease_expires_at"],
            cancel_requested=bool(row["cancel_requested"]), last_error=row["last_error"],
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )

    def enqueue(
        self, kind: str, logical_job_id: str, payload: dict[str, Any], *,
        priority: int = 100, max_attempts: int = 3, delay_seconds: float = 0.0,
        queue_id: str | None = None,
    ) -> QueueJob:
        now = time.time()
        queue_id = queue_id or f"q_{uuid.uuid4().hex[:16]}"
        with self._connect() as db:
            db.execute(
                """INSERT INTO queue_jobs
                (id,kind,logical_job_id,payload_json,status,priority,attempts,max_attempts,
                 available_at,created_at,updated_at)
                VALUES (?,?,?,?, 'queued', ?,0,?,?,?,?)""",
                (queue_id, kind, logical_job_id, json.dumps(payload, ensure_ascii=False),
                 int(priority), max(1, int(max_attempts)), now + max(0.0, delay_seconds), now, now),
            )
        return self.get(queue_id)

    def recover_expired(self, *, now: float | None = None) -> int:
        now = time.time() if now is None else float(now)
        with self._connect() as db:
            cur = db.execute(
                """UPDATE queue_jobs
                   SET status='queued', leased_by=NULL, lease_expires_at=NULL,
                       available_at=?, updated_at=?, last_error=COALESCE(last_error,'worker lease expired')
                   WHERE status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?""",
                (now, now, now),
            )
            return int(cur.rowcount)

    def lease(
        self, worker_id: str, *, lease_seconds: float = 120.0,
        kinds: Iterable[str] | None = None,
    ) -> QueueJob | None:
        now = time.time()
        kinds = [str(x) for x in (kinds or [])]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """UPDATE queue_jobs SET status='queued', leased_by=NULL, lease_expires_at=NULL,
                       available_at=?, updated_at=?
                       WHERE status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?""",
                    (now, now, now),
                )
                where = "status='queued' AND available_at<=? AND cancel_requested=0"
                params: list[Any] = [now]
                if kinds:
                    where += " AND kind IN (" + ",".join("?" for _ in kinds) + ")"
                    params.extend(kinds)
                row = db.execute(
                    f"SELECT * FROM queue_jobs WHERE {where} ORDER BY priority ASC, created_at ASC LIMIT 1",
                    params,
                ).fetchone()
                if row is None:
                    db.execute("COMMIT")
                    return None
                expires = now + max(5.0, float(lease_seconds))
                cur = db.execute(
                    """UPDATE queue_jobs SET status='running', leased_by=?, lease_expires_at=?,
                       attempts=attempts+1, updated_at=?
                       WHERE id=? AND status='queued'""",
                    (worker_id, expires, now, row["id"]),
                )
                if cur.rowcount != 1:
                    db.execute("ROLLBACK")
                    return None
                claimed = db.execute("SELECT * FROM queue_jobs WHERE id=?", (row["id"],)).fetchone()
                db.execute("COMMIT")
                return self._row(claimed)
            except Exception:
                db.execute("ROLLBACK")
                raise

    def heartbeat(self, queue_id: str, worker_id: str, *, lease_seconds: float = 120.0) -> bool:
        now = time.time()
        with self._connect() as db:
            cur = db.execute(
                """UPDATE queue_jobs SET lease_expires_at=?, updated_at=?
                   WHERE id=? AND status='running' AND leased_by=?""",
                (now + max(5.0, lease_seconds), now, queue_id, worker_id),
            )
            return cur.rowcount == 1

    def heartbeat_worker(self, worker_id: str, *, pid: int, hostname: str, active_job_id: str | None = None) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute(
                """INSERT INTO worker_heartbeats(worker_id,pid,hostname,last_seen,active_job_id)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(worker_id) DO UPDATE SET pid=excluded.pid, hostname=excluded.hostname,
                   last_seen=excluded.last_seen, active_job_id=excluded.active_job_id""",
                (worker_id, int(pid), hostname, now, active_job_id),
            )

    def workers(self, *, active_within_seconds: float = 30.0) -> list[dict[str, Any]]:
        cutoff = time.time() - max(1.0, active_within_seconds)
        with self._connect() as db:
            rows = db.execute(
                "SELECT worker_id,pid,hostname,last_seen,active_job_id FROM worker_heartbeats WHERE last_seen>=? ORDER BY last_seen DESC",
                (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete(self, queue_id: str, worker_id: str | None = None) -> bool:
        now = time.time()
        sql = "UPDATE queue_jobs SET status='complete', leased_by=NULL, lease_expires_at=NULL, updated_at=? WHERE id=? AND status='running'"
        params: list[Any] = [now, queue_id]
        if worker_id is not None:
            sql += " AND leased_by=?"
            params.append(worker_id)
        with self._connect() as db:
            return db.execute(sql, params).rowcount == 1

    def mark_cancelled(self, queue_id: str) -> bool:
        now = time.time()
        with self._connect() as db:
            return db.execute(
                "UPDATE queue_jobs SET status='cancelled', leased_by=NULL, lease_expires_at=NULL, updated_at=? WHERE id=?",
                (now, queue_id),
            ).rowcount == 1

    def fail(self, queue_id: str, error: str, *, retry_delay_seconds: float = 2.0) -> QueueJob:
        now = time.time()
        with self._connect() as db:
            row = db.execute("SELECT * FROM queue_jobs WHERE id=?", (queue_id,)).fetchone()
            if row is None:
                raise KeyError(queue_id)
            terminal = int(row["attempts"]) >= int(row["max_attempts"])
            status = "failed" if terminal else "queued"
            db.execute(
                """UPDATE queue_jobs SET status=?, leased_by=NULL, lease_expires_at=NULL,
                   available_at=?, last_error=?, updated_at=? WHERE id=?""",
                (status, now if terminal else now + max(0.0, retry_delay_seconds), error[:4000], now, queue_id),
            )
        return self.get(queue_id)

    def request_cancel(self, *, queue_id: str | None = None, logical_job_id: str | None = None) -> int:
        if not queue_id and not logical_job_id:
            raise ValueError("queue_id or logical_job_id is required")
        now = time.time()
        clause, value = ("id=?", queue_id) if queue_id else ("logical_job_id=?", logical_job_id)
        with self._connect() as db:
            cur = db.execute(
                f"""UPDATE queue_jobs SET cancel_requested=1,
                    status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,
                    updated_at=? WHERE {clause} AND status IN ('queued','running')""",
                (now, value),
            )
            return int(cur.rowcount)

    def get(self, queue_id: str) -> QueueJob:
        with self._connect() as db:
            row = db.execute("SELECT * FROM queue_jobs WHERE id=?", (queue_id,)).fetchone()
        item = self._row(row)
        if item is None:
            raise KeyError(queue_id)
        return item

    def list(self, *, limit: int = 100, status: str | None = None) -> list[QueueJob]:
        sql = "SELECT * FROM queue_jobs"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._row(x) for x in rows if x is not None]

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute("SELECT status, COUNT(*) n FROM queue_jobs GROUP BY status").fetchall()
        out = {str(r["status"]): int(r["n"]) for r in rows}
        return {
            "queued": out.get("queued", 0), "running": out.get("running", 0),
            "complete": out.get("complete", 0), "failed": out.get("failed", 0),
            "cancelled": out.get("cancelled", 0), "total": sum(out.values()),
        }
