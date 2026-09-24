import hashlib
from pathlib import Path

import pytest

from contextmesh.uploads import UploadSessionStore


def test_local_resumable_upload_can_skip_existing_parts(tmp_path: Path):
    store = UploadSessionStore(tmp_path / "uploads.sqlite3", tmp_path / "staging")
    payload = b"a" * (1024 * 1024) + b"tail"
    digest = hashlib.sha256(payload).hexdigest()
    session = store.create("big.bin", len(payload), sha256=digest, part_size=1024 * 1024)

    first = payload[: 1024 * 1024]
    second = payload[1024 * 1024 :]
    store.put_local_part(session.id, 1, first, expected_sha256=hashlib.sha256(first).hexdigest())

    status = store.status(session.id)
    assert status["uploaded_parts"] == 1
    assert status["missing_parts"] == [2]

    resumed = UploadSessionStore(tmp_path / "uploads.sqlite3", tmp_path / "staging")
    assert resumed.status(session.id)["missing_parts"] == [2]
    resumed.put_local_part(session.id, 2, second)

    completed = resumed.complete_local(session.id, tmp_path / "completed")
    assert completed.status == "complete"
    assert Path(completed.completed_path).read_bytes() == payload
    assert resumed.status(session.id)["progress"] == 1.0


def test_part_checksum_mismatch_is_rejected(tmp_path: Path):
    store = UploadSessionStore(tmp_path / "uploads.sqlite3", tmp_path / "staging")
    session = store.create("x.bin", 4, part_size=1024 * 1024)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        store.put_local_part(session.id, 1, b"data", expected_sha256="deadbeef")


def test_complete_rejects_missing_parts(tmp_path: Path):
    store = UploadSessionStore(tmp_path / "uploads.sqlite3", tmp_path / "staging")
    session = store.create("two.bin", 1024 * 1024 + 1, part_size=1024 * 1024)
    store.put_local_part(session.id, 1, b"a" * (1024 * 1024))
    with pytest.raises(ValueError, match="missing upload parts"):
        store.complete_local(session.id, tmp_path / "completed")
