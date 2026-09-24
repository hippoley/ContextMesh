import time
from pathlib import Path

from contextmesh.jobqueue import SQLiteJobQueue


def test_queue_survives_new_process_instance(tmp_path: Path):
    path = tmp_path / "jobs.sqlite3"
    q1 = SQLiteJobQueue(path)
    created = q1.enqueue("evaluation", "job-1", {"corpus_id": "c1"}, max_attempts=2)

    q2 = SQLiteJobQueue(path)
    leased = q2.lease("worker-a", lease_seconds=30)
    assert leased is not None
    assert leased.id == created.id
    assert leased.logical_job_id == "job-1"
    assert leased.attempts == 1
    assert q2.complete(leased.id, "worker-a") is True
    assert q1.get(leased.id).status == "complete"


def test_expired_worker_lease_is_reclaimed(tmp_path: Path):
    q = SQLiteJobQueue(tmp_path / "jobs.sqlite3")
    q.enqueue("ingest", "ing-1", {"paths": ["a.pdf"]})
    first = q.lease("worker-dead", lease_seconds=5)
    assert first is not None

    # Force lease expiry without sleeping.
    with q._connect() as db:
        db.execute("UPDATE queue_jobs SET lease_expires_at=? WHERE id=?", (time.time() - 1, first.id))

    second = q.lease("worker-recovery", lease_seconds=30)
    assert second is not None
    assert second.id == first.id
    assert second.attempts == 2
    assert second.leased_by == "worker-recovery"


def test_cancelled_queued_job_is_never_leased(tmp_path: Path):
    q = SQLiteJobQueue(tmp_path / "jobs.sqlite3")
    item = q.enqueue("evaluation", "job-cancel", {})
    assert q.request_cancel(logical_job_id="job-cancel") == 1
    assert q.get(item.id).status == "cancelled"
    assert q.lease("worker") is None


def test_failed_job_retries_then_becomes_terminal(tmp_path: Path):
    q = SQLiteJobQueue(tmp_path / "jobs.sqlite3")
    item = q.enqueue("evaluation", "job-retry", {}, max_attempts=2)
    one = q.lease("w1")
    assert one and one.attempts == 1
    assert q.fail(one.id, "boom", retry_delay_seconds=0).status == "queued"
    two = q.lease("w2")
    assert two and two.attempts == 2
    assert q.fail(two.id, "boom again", retry_delay_seconds=0).status == "failed"


def test_worker_heartbeat_is_visible(tmp_path: Path):
    q = SQLiteJobQueue(tmp_path / "jobs.sqlite3")
    q.heartbeat_worker("worker-1", pid=123, hostname="host-a", active_job_id="q1")
    rows = q.workers(active_within_seconds=60)
    assert len(rows) == 1
    assert rows[0]["worker_id"] == "worker-1"
    assert rows[0]["active_job_id"] == "q1"
