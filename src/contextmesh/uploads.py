from __future__ import annotations

import hashlib
import math
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class UploadSession:
    id: str
    filename: str
    size_bytes: int
    sha256: str | None
    backend: str
    part_size: int
    status: str
    completed_path: str | None
    object_key: str | None
    remote_upload_id: str | None
    created_at: float
    updated_at: float


class UploadSessionStore:
    """Durable upload-session metadata plus local resumable part storage."""

    def __init__(self, db_path: str | Path, staging_root: str | Path):
        self.db_path = Path(db_path)
        self.staging_root = Path(staging_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS upload_sessions (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT,
                    backend TEXT NOT NULL,
                    part_size INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    completed_path TEXT,
                    object_key TEXT,
                    remote_upload_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS upload_parts (
                    session_id TEXT NOT NULL,
                    part_number INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT,
                    etag TEXT,
                    path TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(session_id, part_number)
                );
                CREATE INDEX IF NOT EXISTS idx_upload_status
                    ON upload_sessions(status, updated_at DESC);
                """
            )

    @staticmethod
    def _safe_name(filename: str) -> str:
        name = Path(filename or "upload.bin").name
        return name.replace("\x00", "") or "upload.bin"

    @staticmethod
    def _session(row: sqlite3.Row | None) -> UploadSession | None:
        if row is None:
            return None
        return UploadSession(
            id=row["id"], filename=row["filename"], size_bytes=int(row["size_bytes"]),
            sha256=row["sha256"], backend=row["backend"], part_size=int(row["part_size"]),
            status=row["status"], completed_path=row["completed_path"], object_key=row["object_key"],
            remote_upload_id=row["remote_upload_id"], created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def create(
        self, filename: str, size_bytes: int, *, sha256: str | None = None,
        part_size: int = 8 * 1024 * 1024, backend: str = "local",
        object_key: str | None = None, remote_upload_id: str | None = None,
    ) -> UploadSession:
        size_bytes = int(size_bytes)
        part_size = int(part_size)
        if size_bytes < 0:
            raise ValueError("size_bytes must be >= 0")
        if part_size < 1024 * 1024:
            raise ValueError("part_size must be at least 1 MiB")
        if backend not in {"local", "s3"}:
            raise ValueError(f"unsupported upload backend: {backend}")
        now = time.time()
        session_id = f"up_{uuid.uuid4().hex[:16]}"
        filename = self._safe_name(filename)
        with self._connect() as db:
            db.execute(
                """INSERT INTO upload_sessions
                   (id,filename,size_bytes,sha256,backend,part_size,status,completed_path,
                    object_key,remote_upload_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,'created',NULL,?,?,?,?)""",
                (session_id, filename, size_bytes, sha256, backend, part_size,
                 object_key, remote_upload_id, now, now),
            )
        (self.staging_root / session_id).mkdir(parents=True, exist_ok=True)
        return self.get(session_id)

    def get(self, session_id: str) -> UploadSession:
        with self._connect() as db:
            row = db.execute("SELECT * FROM upload_sessions WHERE id=?", (session_id,)).fetchone()
        session = self._session(row)
        if session is None:
            raise KeyError(session_id)
        return session

    def set_remote(self, session_id: str, *, object_key: str, remote_upload_id: str) -> UploadSession:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "UPDATE upload_sessions SET object_key=?, remote_upload_id=?, status='uploading', updated_at=? WHERE id=?",
                (object_key, remote_upload_id, now, session_id),
            )
        return self.get(session_id)

    def parts(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT part_number,size_bytes,sha256,etag,path,updated_at FROM upload_parts WHERE session_id=? ORDER BY part_number",
                (session_id,),
            ).fetchall()
        return [dict(x) for x in rows]

    def status(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        parts = self.parts(session_id)
        expected_parts = math.ceil(session.size_bytes / session.part_size) if session.size_bytes else 0
        uploaded = sum(int(x["size_bytes"]) for x in parts)
        present = {int(x["part_number"]) for x in parts}
        missing = [x for x in range(1, expected_parts + 1) if x not in present]
        return {
            **asdict(session),
            "expected_parts": expected_parts,
            "uploaded_parts": len(parts),
            "uploaded_bytes": uploaded,
            "missing_parts": missing,
            "parts": parts,
            "progress": uploaded / session.size_bytes if session.size_bytes else 1.0,
        }

    def put_local_part(
        self, session_id: str, part_number: int, data: bytes, *,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        session = self.get(session_id)
        if session.backend != "local":
            raise ValueError("local part upload is only valid for local backend sessions")
        if session.status in {"complete", "aborted"}:
            raise ValueError(f"upload session is {session.status}")
        part_number = int(part_number)
        expected_parts = math.ceil(session.size_bytes / session.part_size) if session.size_bytes else 0
        if part_number < 1 or (expected_parts and part_number > expected_parts):
            raise ValueError("invalid part number")
        if len(data) > session.part_size:
            raise ValueError("part exceeds configured part_size")
        if expected_parts and part_number < expected_parts and len(data) != session.part_size:
            raise ValueError("non-final part must exactly match part_size")
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise ValueError("part SHA-256 mismatch")
        d = self.staging_root / session_id
        d.mkdir(parents=True, exist_ok=True)
        final = d / f"part-{part_number:05d}.bin"
        tmp = final.with_suffix(f".tmp-{uuid.uuid4().hex}")
        tmp.write_bytes(data)
        os.replace(tmp, final)
        now = time.time()
        with self._connect() as db:
            db.execute(
                """INSERT INTO upload_parts(session_id,part_number,size_bytes,sha256,etag,path,updated_at)
                   VALUES(?,?,?,?,NULL,?,?)
                   ON CONFLICT(session_id,part_number) DO UPDATE SET
                   size_bytes=excluded.size_bytes, sha256=excluded.sha256,
                   path=excluded.path, updated_at=excluded.updated_at""",
                (session_id, part_number, len(data), digest, str(final), now),
            )
            db.execute("UPDATE upload_sessions SET status='uploading', updated_at=? WHERE id=?", (now, session_id))
        return {"part_number": part_number, "size_bytes": len(data), "sha256": digest}

    def record_remote_part(self, session_id: str, part_number: int, *, etag: str, size_bytes: int = 0) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute(
                """INSERT INTO upload_parts(session_id,part_number,size_bytes,sha256,etag,path,updated_at)
                   VALUES(?,?,?,NULL,?,NULL,?)
                   ON CONFLICT(session_id,part_number) DO UPDATE SET
                   size_bytes=excluded.size_bytes, etag=excluded.etag, updated_at=excluded.updated_at""",
                (session_id, int(part_number), int(size_bytes), etag, now),
            )
            db.execute("UPDATE upload_sessions SET status='uploading', updated_at=? WHERE id=?", (now, session_id))

    def complete_local(self, session_id: str, destination_dir: str | Path) -> UploadSession:
        session = self.get(session_id)
        if session.backend != "local":
            raise ValueError("not a local upload session")
        status = self.status(session_id)
        if status["missing_parts"]:
            raise ValueError(f"missing upload parts: {status['missing_parts'][:20]}")
        if status["uploaded_bytes"] != session.size_bytes:
            raise ValueError(f"size mismatch: expected {session.size_bytes}, got {status['uploaded_bytes']}")
        destination = Path(destination_dir)
        destination.mkdir(parents=True, exist_ok=True)
        stem, suffix = Path(session.filename).stem, Path(session.filename).suffix
        final = destination / session.filename
        n = 2
        while final.exists():
            final = destination / f"{stem}-{n}{suffix}"
            n += 1
        tmp = destination / f".{final.name}.assembling-{uuid.uuid4().hex}"
        h = hashlib.sha256()
        with tmp.open("wb") as out:
            for part in self.parts(session_id):
                p = Path(str(part["path"]))
                data = p.read_bytes()
                out.write(data)
                h.update(data)
        digest = h.hexdigest()
        if session.sha256 and digest.lower() != session.sha256.lower():
            tmp.unlink(missing_ok=True)
            raise ValueError("final SHA-256 mismatch")
        os.replace(tmp, final)
        now = time.time()
        with self._connect() as db:
            db.execute(
                "UPDATE upload_sessions SET status='complete', completed_path=?, sha256=COALESCE(sha256,?), updated_at=? WHERE id=?",
                (str(final), digest, now, session_id),
            )
        return self.get(session_id)

    def mark_remote_complete(self, session_id: str, completed_path: str) -> UploadSession:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "UPDATE upload_sessions SET status='complete', completed_path=?, updated_at=? WHERE id=?",
                (completed_path, now, session_id),
            )
        return self.get(session_id)

    def abort(self, session_id: str) -> UploadSession:
        session = self.get(session_id)
        shutil.rmtree(self.staging_root / session_id, ignore_errors=True)
        now = time.time()
        with self._connect() as db:
            db.execute("UPDATE upload_sessions SET status='aborted', updated_at=? WHERE id=?", (now, session_id))
        return self.get(session_id)


class S3MultipartAdapter:
    """Optional S3/MinIO multipart transport loaded only when configured."""

    def __init__(
        self, *, bucket: str, endpoint_url: str | None = None,
        region_name: str | None = None, prefix: str = "contextmesh/uploads",
    ):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("S3 multipart requires the optional s3 dependency") from exc
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region_name or None)

    @classmethod
    def from_env(cls) -> "S3MultipartAdapter":
        bucket = os.getenv("CONTEXTMESH_S3_BUCKET")
        if not bucket:
            raise RuntimeError("CONTEXTMESH_S3_BUCKET is required for s3 upload backend")
        return cls(
            bucket=bucket,
            endpoint_url=os.getenv("CONTEXTMESH_S3_ENDPOINT_URL"),
            region_name=os.getenv("CONTEXTMESH_S3_REGION"),
            prefix=os.getenv("CONTEXTMESH_S3_PREFIX", "contextmesh/uploads"),
        )

    def begin(self, session_id: str, filename: str, content_type: str | None = None) -> tuple[str, str]:
        key = f"{self.prefix}/{session_id}/{Path(filename).name}"
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if content_type:
            kwargs["ContentType"] = content_type
        response = self.client.create_multipart_upload(**kwargs)
        return key, str(response["UploadId"])

    def presign_part(self, *, key: str, upload_id: str, part_number: int, expires_seconds: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": self.bucket, "Key": key, "UploadId": upload_id, "PartNumber": int(part_number)},
            ExpiresIn=int(expires_seconds),
        )

    def complete(self, *, key: str, upload_id: str, parts: list[dict[str, Any]]) -> str:
        normalized = [
            {"PartNumber": int(x["part_number"]), "ETag": str(x["etag"])}
            for x in sorted(parts, key=lambda x: int(x["part_number"]))
        ]
        self.client.complete_multipart_upload(
            Bucket=self.bucket, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": normalized},
        )
        return f"s3://{self.bucket}/{key}"

    def abort(self, *, key: str, upload_id: str) -> None:
        self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)

    def materialize(self, *, key: str, destination: str | Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(destination))
        return destination
