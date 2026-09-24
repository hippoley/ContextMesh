from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
import os
import shutil
import socket
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .benchmark import ScorePreservationBenchmark
from .events import EventBus
from .evidence import evidence_kind_counts
from .explorer import build_explorer_groups
from .ingest import ingest_paths
from .judges import HeuristicJudge, OpenAICompatibleJudge
from .jobqueue import QueueJob, SQLiteJobQueue
from .providers import build_judge_from_route, provider_catalog
from .models import AssetIngestState, EvaluationCheckpoint, EvaluationState, IngestJob, IngestStatus, ModelRoute
from .observability import collect_runtime_telemetry
from .reader import CorpusReader
from .runtime import ProgressiveEvaluator
from .store import FileContextStore
from .audit import audit_corpus

DATA_ROOT = Path(os.getenv("CONTEXTMESH_DATA", ".contextmesh"))
UPLOAD_ROOT = DATA_ROOT / "uploads"
STORE = FileContextStore(DATA_ROOT / "store")
WEB_ROOT = Path(__file__).with_name("web")
EVENTS = EventBus()
QUEUE = SQLiteJobQueue(DATA_ROOT / "jobs.sqlite3")
_WORKER_STOP = threading.Event()
_WORKER_THREAD: threading.Thread | None = None

def _embedded_worker_enabled() -> bool:
    return os.getenv("CONTEXTMESH_EMBEDDED_WORKER", "1").strip().lower() not in {"0", "false", "no", "off"}

def _ensure_embedded_worker() -> None:
    global _WORKER_THREAD
    if not _embedded_worker_enabled():
        return
    if _WORKER_THREAD and _WORKER_THREAD.is_alive():
        return
    _WORKER_STOP.clear()
    _WORKER_THREAD = threading.Thread(
        target=run_worker_loop,
        kwargs={"stop_event": _WORKER_STOP, "poll_seconds": 0.05},
        daemon=True,
        name="contextmesh-embedded-worker",
    )
    _WORKER_THREAD.start()

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    STORE.reconcile_interrupted_jobs()
    QUEUE.recover_expired()
    _ensure_embedded_worker()
    try:
        yield
    finally:
        _WORKER_STOP.set()
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            _WORKER_THREAD.join(timeout=2.0)

app = FastAPI(title="ContextMesh", version="0.13.0", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_ROOT)), name="static")



class EvaluateRequest(BaseModel):
    corpus_id: str
    question: str
    answer: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    route_id: str | None = None
    order: list[str] | None = None
    job_id: str | None = None
    resume: bool = False
    max_blocks: int | None = None
    reduction_batch_size: int = 32
    max_workers: int = 1
    retry_attempts: int = 1


class BenchmarkRequest(EvaluateRequest):
    tolerance: float = 1.0
    max_direct_chars: int = 250_000


class PreflightRequest(BaseModel):
    corpus_id: str
    route_id: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


@app.get("/", include_in_schema=False)
def workspace_page():
    return FileResponse(WEB_ROOT / "workspace.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(WEB_ROOT / "admin.html")


@app.get("/health")
def health():
    return {"ok": True, "version": "0.13.0", "queue": QUEUE.stats(), "workers": len(QUEUE.workers())}


@app.get("/api/events")
def event_stream(job_id: str | None = None, corpus_id: str | None = None, event: str | None = None):
    subscription = EVENTS.subscribe()
    def predicate(item: dict) -> bool:
        if job_id and item.get("job_id") != job_id:
            return False
        if corpus_id and item.get("corpus_id") != corpus_id:
            return False
        if event and item.get("event") != event:
            return False
        return True
    return StreamingResponse(
        EVENTS.iter_sse(subscription, predicate=predicate),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _save_uploads(files: list[UploadFile], corpus_id: str) -> list[Path]:
    target = UPLOAD_ROOT / corpus_id
    target.mkdir(parents=True, exist_ok=True)
    max_file = int(os.getenv("CONTEXTMESH_MAX_FILE_BYTES", str(2 * 1024**3)))
    max_total = int(os.getenv("CONTEXTMESH_MAX_UPLOAD_BYTES", str(10 * 1024**3)))
    total = 0
    paths: list[Path] = []
    used: set[str] = set()
    for idx, f in enumerate(files):
        raw_name = Path(f.filename or f"asset_{idx}").name
        stem, suffix = Path(raw_name).stem, Path(raw_name).suffix
        name = raw_name
        n = 2
        while name.lower() in used or (target / name).exists():
            name = f"{stem}-{n}{suffix}"
            n += 1
        used.add(name.lower())
        p = target / name
        written = 0
        try:
            with p.open("wb") as out:
                while True:
                    chunk = f.file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    total += len(chunk)
                    if written > max_file:
                        raise ValueError(f"file exceeds upload limit ({max_file} bytes): {raw_name}")
                    if total > max_total:
                        raise ValueError(f"upload batch exceeds limit ({max_total} bytes)")
                    out.write(chunk)
        except Exception:
            p.unlink(missing_ok=True)
            raise
        paths.append(p)
    return paths


# ---- Ingest queue ------------------------------------------------------------
def _run_ingest_job(job_id: str, corpus_id: str, paths: list[Path]) -> None:
    job = STORE.get_ingest_job(job_id)
    job.status = IngestStatus.RUNNING
    job.message = "Parsing files into addressable context blocks"
    STORE.put_ingest_job(job)
    EVENTS.publish("ingest", {"job_id": job_id, "corpus_id": corpus_id, "status": job.status.value, "progress": job.progress})

    def progress(event: dict) -> None:
        current = STORE.get_ingest_job(job_id)
        path = str(event.get("path", ""))
        asset = next((x for x in current.assets if x.path == path), None)
        if event.get("phase") == "file_started" and asset:
            asset.status = IngestStatus.RUNNING
            asset.message = "Parsing"
        elif event.get("phase") == "file_complete" and asset:
            partial = str(event.get("ingest_status")) == "partial" or int(event.get("unresolved_units") or 0) > 0
            asset.status = IngestStatus.PARTIAL if partial else IngestStatus.COMPLETE
            asset.required_blocks = int(event.get("required_blocks") or 0)
            asset.semantic_coverage = float(event.get("semantic_coverage") or 0.0)
            asset.unresolved_units = int(event.get("unresolved_units") or 0)
            asset.message = f"{asset.required_blocks} coverage blocks · semantic {asset.semantic_coverage:.1%}"
            current.completed_files = sum(1 for x in current.assets if x.status in {IngestStatus.COMPLETE, IngestStatus.PARTIAL})
        elif event.get("phase") == "file_failed" and asset:
            asset.status = IngestStatus.FAILED
            asset.semantic_coverage = 0.0
            asset.unresolved_units = int(event.get("unresolved_units") or 1)
            asset.message = str(event.get("error") or "parse failed")
            current.completed_files = sum(1 for x in current.assets if x.status in {IngestStatus.COMPLETE, IngestStatus.PARTIAL, IngestStatus.FAILED})
        current.message = str(event.get("phase", "running"))
        STORE.put_ingest_job(current)
        EVENTS.publish(
            "ingest",
            {
                "job_id": job_id,
                "corpus_id": corpus_id,
                "status": current.status.value,
                "progress": current.progress,
                "completed_files": current.completed_files,
                "total_files": current.total_files,
                "path": path,
                "phase": event.get("phase"),
            },
        )

    try:
        manifest = ingest_paths(paths, STORE, corpus_id, progress_callback=progress)
        job = STORE.get_ingest_job(job_id)
        job.status = IngestStatus.COMPLETE if manifest.coverage_ready else IngestStatus.PARTIAL
        job.completed_files = job.total_files
        job.manifest = manifest
        job.message = (
            f"Ready: {manifest.required_blocks} required blocks" if manifest.coverage_ready
            else f"Partial: semantic {manifest.semantic_coverage:.1%}, unresolved units={manifest.unresolved_units}"
        )
        report_by_path = {r.path: r for r in manifest.asset_reports}
        for asset in job.assets:
            report = report_by_path.get(asset.path)
            if report:
                asset.semantic_coverage = report.semantic_coverage
                asset.unresolved_units = report.unresolved_units
                asset.required_blocks = report.resolved_units
                asset.status = IngestStatus.COMPLETE if report.status == "complete" else IngestStatus.PARTIAL if report.status == "partial" else IngestStatus.FAILED
                asset.message = "; ".join(report.warnings) or f"semantic {report.semantic_coverage:.1%}"
        STORE.put_ingest_job(job)
        EVENTS.publish("ingest", {
            "job_id": job_id, "corpus_id": corpus_id, "status": job.status.value, "progress": 1.0,
            "manifest": manifest.model_dump(), "ingest_coverage": manifest.ingest_coverage,
            "semantic_coverage": manifest.semantic_coverage, "unresolved_units": manifest.unresolved_units,
        })
    except Exception as exc:
        job = STORE.get_ingest_job(job_id)
        job.status = IngestStatus.FAILED
        job.message = f"{type(exc).__name__}: {exc}"
        for asset in job.assets:
            if asset.status == IngestStatus.RUNNING:
                asset.status = IngestStatus.FAILED
                asset.message = job.message
        STORE.put_ingest_job(job)
        EVENTS.publish("ingest", {"job_id": job_id, "corpus_id": corpus_id, "status": "failed", "progress": job.progress, "error": job.message})


@app.post("/api/ingest-jobs")
async def create_ingest_job(files: list[UploadFile] = File(...)):
    corpus_id = f"corp_{uuid.uuid4().hex[:12]}"
    try:
        paths = _save_uploads(files, corpus_id)
    except ValueError as e:
        shutil.rmtree(UPLOAD_ROOT / corpus_id, ignore_errors=True)
        raise HTTPException(status_code=413, detail=str(e)) from e
    job_id = f"ingest_{uuid.uuid4().hex[:12]}"
    job = IngestJob(
        job_id=job_id,
        corpus_id=corpus_id,
        total_files=len(paths),
        total_bytes=sum(p.stat().st_size for p in paths),
        assets=[AssetIngestState(filename=p.name, path=str(p), bytes=p.stat().st_size) for p in paths],
    )
    STORE.put_ingest_job(job)
    queued = QUEUE.enqueue(
        "ingest", job_id,
        {"job_id": job_id, "corpus_id": corpus_id, "paths": [str(p) for p in paths]},
        max_attempts=2,
    )
    EVENTS.publish("queue", {"queue_id": queued.id, "job_id": job_id, "corpus_id": corpus_id, "kind": "ingest", "status": "queued"})
    _ensure_embedded_worker()
    return job.model_copy(update={"message": f"Queued as {queued.id}"})


@app.get("/api/ingest-jobs")
def list_ingest_jobs():
    return {"jobs": STORE.list_ingest_jobs()}


@app.get("/api/ingest-jobs/{job_id}")
def ingest_job(job_id: str):
    try:
        return STORE.get_ingest_job(job_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="ingest job not found") from e

@app.post("/api/ingest-jobs/{job_id}/retry")
def retry_ingest_job(job_id: str):
    try:
        job = STORE.get_ingest_job(job_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="ingest job not found") from e
    paths = [Path(a.path) for a in job.assets if Path(a.path).is_file()]
    if not paths:
        raise HTTPException(status_code=409, detail="no original upload files remain for retry")
    job.status = IngestStatus.QUEUED
    job.completed_files = 0
    job.message = "Retry queued"
    for asset in job.assets:
        asset.status = IngestStatus.QUEUED
        asset.message = ""
    STORE.put_ingest_job(job)
    queued = QUEUE.enqueue(
        "ingest", job.job_id,
        {"job_id": job.job_id, "corpus_id": job.corpus_id, "paths": [str(p) for p in paths]},
        max_attempts=2,
    )
    _ensure_embedded_worker()
    return {"accepted": True, "job_id": job.job_id, "corpus_id": job.corpus_id, "queue_id": queued.id}


# Backward-compatible synchronous ingest endpoint.
@app.post("/corpora")
async def create_corpus(files: list[UploadFile] = File(...)):
    corpus_id = f"corp_{uuid.uuid4().hex[:12]}"
    try:
        paths = _save_uploads(files, corpus_id)
    except ValueError as e:
        shutil.rmtree(UPLOAD_ROOT / corpus_id, ignore_errors=True)
        raise HTTPException(status_code=413, detail=str(e)) from e
    try:
        return ingest_paths(paths, STORE, corpus_id)
    except ValueError as e:
        shutil.rmtree(UPLOAD_ROOT / corpus_id, ignore_errors=True)
        STORE.delete_corpus(corpus_id)
        raise HTTPException(status_code=415, detail=str(e)) from e


@app.get("/corpora/{corpus_id}")
def corpus(corpus_id: str):
    try:
        return STORE.get_manifest(corpus_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e


@app.get("/api/corpora/{corpus_id}/storage")
def corpus_storage(corpus_id: str):
    try:
        return STORE.block_store_stats(corpus_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e


@app.get("/api/corpora/{corpus_id}/audit")
def corpus_audit(corpus_id: str):
    try:
        return audit_corpus(STORE, corpus_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e


@app.get("/api/corpora")
def list_corpora():
    return {"corpora": STORE.list_manifests()}


@app.get("/api/corpora/{corpus_id}/catalog")
def corpus_catalog(corpus_id: str):
    try:
        return {"corpus_id": corpus_id, **STORE.catalog_stats(corpus_id)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e


@app.delete("/api/corpora/{corpus_id}")
def delete_corpus(corpus_id: str):
    deleted = STORE.delete_corpus(corpus_id)
    shutil.rmtree(UPLOAD_ROOT / corpus_id, ignore_errors=True)
    if not deleted:
        raise HTTPException(status_code=404, detail="corpus not found")
    return {"ok": True, "corpus_id": corpus_id}


# ---- Model routing -----------------------------------------------------------

@app.get("/api/admin/provider-catalog")
def get_provider_catalog():
    return {"providers": provider_catalog()}

@app.get("/api/admin/model-routes")
def list_model_routes():
    return {"routes": STORE.list_model_routes()}


@app.put("/api/admin/model-routes/{route_id}")
def put_model_route(route_id: str, route: ModelRoute):
    if route.id != route_id:
        route = route.model_copy(update={"id": route_id})
    return STORE.upsert_model_route(route)


@app.delete("/api/admin/model-routes/{route_id}")
def delete_model_route(route_id: str):
    if not STORE.delete_model_route(route_id):
        raise HTTPException(status_code=404, detail="route not found")
    return {"ok": True}

@app.post("/api/admin/model-routes/{route_id}/test")
def test_model_route(route_id: str):
    route = next((r for r in STORE.list_model_routes() if r.id == route_id and r.enabled), None)
    if not route:
        raise HTTPException(status_code=404, detail="enabled route not found")
    judge = build_judge_from_route(route)
    try:
        return judge.health_check()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


def _route_for_request(req: EvaluateRequest) -> ModelRoute | None:
    if not req.route_id:
        return None
    return next((r for r in STORE.list_model_routes() if r.id == req.route_id and r.enabled), None)

def _effective_workers(req: EvaluateRequest) -> int:
    route = _route_for_request(req)
    if route and route.max_parallel_requests:
        return max(1, min(int(req.max_workers), int(route.max_parallel_requests)))
    return max(1, int(req.max_workers))

def _judge_for_request(req: EvaluateRequest):
    if req.route_id:
        route = _route_for_request(req)
        if not route:
            raise ValueError(f"enabled model route not found: {req.route_id}")
        return build_judge_from_route(route)
    if req.model and req.base_url:
        return OpenAICompatibleJudge(req.model, req.base_url, req.api_key or "EMPTY")
    return HeuristicJudge()


# ---- Full-coverage evaluation jobs ------------------------------------------
def _evaluation_progress(data: dict) -> None:
    EVENTS.publish("evaluation", data)


def _run_evaluation_job(req: EvaluateRequest, job_id: str) -> None:
    try:
        judge = _judge_for_request(req)
        ProgressiveEvaluator(
            STORE,
            judge,
            reduction_batch_size=req.reduction_batch_size,
            max_workers=_effective_workers(req),
            retry_attempts=req.retry_attempts,
            retry_backoff_seconds=0.75,
            progress_callback=_evaluation_progress,
            cancellation_check=STORE.job_cancel_requested,
        ).evaluate(
            req.corpus_id,
            req.question,
            req.answer,
            order=req.order,
            job_id=job_id,
            resume=req.resume,
            max_blocks=None,
        )
    except Exception as exc:
        try:
            cp = STORE.get_checkpoint(req.corpus_id, job_id)
            cp.status = "failed"
            cp.final_rationale = f"{type(exc).__name__}: {exc}"
            STORE.put_checkpoint(cp)
        except Exception:
            pass
        EVENTS.publish("evaluation", {"job_id": job_id, "corpus_id": req.corpus_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})


@app.post("/api/evaluation-jobs")
def create_evaluation_job(req: EvaluateRequest):
    try:
        STORE.get_manifest(req.corpus_id)
        _judge_for_request(req)  # validate route synchronously
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    job_id = req.job_id or f"job_{uuid.uuid4().hex[:12]}"
    req = req.model_copy(update={"job_id": job_id, "resume": False, "max_blocks": None})
    STORE.clear_job_flags(req.corpus_id, job_id)
    queued = QUEUE.enqueue(
        "evaluation", job_id,
        {"request": req.model_dump(mode="json")},
        max_attempts=1,
    )
    EVENTS.publish("evaluation", {"job_id": job_id, "corpus_id": req.corpus_id, "queue_id": queued.id, "status": "queued", "coverage": 0.0})
    _ensure_embedded_worker()
    return {"accepted": True, "job_id": job_id, "queue_id": queued.id, "corpus_id": req.corpus_id, "events": "/api/events"}


@app.post("/api/evaluation-jobs/{corpus_id}/{job_id}/cancel")
def cancel_evaluation_job(corpus_id: str, job_id: str):
    try:
        STORE.get_manifest(corpus_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e
    try:
        cp = STORE.get_checkpoint(corpus_id, job_id)
        if cp.complete:
            raise HTTPException(status_code=409, detail="completed job cannot be cancelled")
    except FileNotFoundError:
        cp = None
    STORE.set_job_flag(corpus_id, job_id, cancel_requested=True)
    QUEUE.request_cancel(logical_job_id=job_id)
    EVENTS.publish("evaluation", {"job_id": job_id, "corpus_id": corpus_id, "status": "cancelling"})
    return {"accepted": True, "job_id": job_id, "status": "cancelling"}

@app.post("/api/evaluation-jobs/{corpus_id}/{job_id}/resume")
def resume_evaluation_job(corpus_id: str, job_id: str, route_id: str | None = None):
    try:
        cp = STORE.get_checkpoint(corpus_id, job_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="evaluation job not found") from e
    if cp.complete:
        return {"accepted": False, "job_id": job_id, "status": "complete"}
    inferred_route = route_id or cp.state.usage.route_id
    req = EvaluateRequest(
        corpus_id=corpus_id, question=cp.state.question, answer=cp.state.answer,
        route_id=inferred_route, job_id=job_id, resume=True, max_workers=4, retry_attempts=2,
    )
    try:
        _judge_for_request(req)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    STORE.clear_job_flags(corpus_id, job_id)
    req = req.model_copy(update={"order": cp.ordered_block_ids, "resume": True})
    queued = QUEUE.enqueue(
        "evaluation", job_id,
        {"request": req.model_dump(mode="json")},
        max_attempts=1,
    )
    EVENTS.publish("evaluation", {"job_id": job_id, "corpus_id": corpus_id, "queue_id": queued.id, "status": "queued"})
    _ensure_embedded_worker()
    return {"accepted": True, "job_id": job_id, "queue_id": queued.id, "corpus_id": corpus_id, "status": "queued"}



def _process_queue_job(item: QueueJob) -> str:
    if item.kind == "ingest":
        payload = item.payload
        _run_ingest_job(
            str(payload["job_id"]),
            str(payload["corpus_id"]),
            [Path(x) for x in payload.get("paths", [])],
        )
        job = STORE.get_ingest_job(str(payload["job_id"]))
        if job.status == IngestStatus.FAILED:
            raise RuntimeError(job.message or "ingest failed")
        return job.status.value

    if item.kind == "evaluation":
        req = EvaluateRequest.model_validate(item.payload["request"])
        _run_evaluation_job(req, req.job_id or item.logical_job_id)
        try:
            cp = STORE.get_checkpoint(req.corpus_id, req.job_id or item.logical_job_id)
        except FileNotFoundError:
            raise RuntimeError("evaluation finished without a checkpoint")
        if cp.status == "failed":
            raise RuntimeError(cp.final_rationale or "evaluation failed")
        return cp.status

    raise ValueError(f"unsupported queue job kind: {item.kind}")


def run_worker_loop(
    *, stop_event: threading.Event | None = None, poll_seconds: float = 0.5,
    lease_seconds: float = 180.0, once: bool = False, worker_id: str | None = None,
) -> None:
    stop_event = stop_event or threading.Event()
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    while not stop_event.is_set():
        QUEUE.heartbeat_worker(worker_id, pid=os.getpid(), hostname=socket.gethostname(), active_job_id=None)
        item = QUEUE.lease(worker_id, lease_seconds=lease_seconds)
        if item is None:
            if once:
                return
            stop_event.wait(max(0.05, poll_seconds))
            continue
        QUEUE.heartbeat_worker(worker_id, pid=os.getpid(), hostname=socket.gethostname(), active_job_id=item.id)
        EVENTS.publish("queue", {"queue_id": item.id, "job_id": item.logical_job_id, "kind": item.kind, "status": "running", "worker_id": worker_id})
        try:
            logical_status = _process_queue_job(item)
            if logical_status == "cancelled":
                QUEUE.mark_cancelled(item.id)
            else:
                QUEUE.complete(item.id, worker_id)
            EVENTS.publish("queue", {"queue_id": item.id, "job_id": item.logical_job_id, "kind": item.kind, "status": logical_status, "worker_id": worker_id})
        except Exception as exc:
            failed = QUEUE.fail(item.id, f"{type(exc).__name__}: {exc}", retry_delay_seconds=min(30.0, 2.0 ** max(0, item.attempts - 1)))
            EVENTS.publish("queue", {"queue_id": item.id, "job_id": item.logical_job_id, "kind": item.kind, "status": failed.status, "error": failed.last_error, "worker_id": worker_id})
        finally:
            QUEUE.heartbeat_worker(worker_id, pid=os.getpid(), hostname=socket.gethostname(), active_job_id=None)
        if once:
            return


@app.get("/api/admin/queue")
def queue_overview(limit: int = Query(100, ge=1, le=1000)):
    return {
        "stats": QUEUE.stats(),
        "workers": QUEUE.workers(),
        "jobs": [asdict(x) for x in QUEUE.list(limit=limit)],
        "backend": "sqlite-wal",
        "scope": "single-host durable queue; run contextmesh worker for process isolation",
    }


@app.post("/api/preflight")
def evaluation_preflight(req: PreflightRequest):
    try:
        eval_req = EvaluateRequest(
            corpus_id=req.corpus_id, question="preflight", answer="preflight",
            route_id=req.route_id, model=req.model, base_url=req.base_url, api_key=req.api_key,
        )
        judge = _judge_for_request(eval_req)
        return ProgressiveEvaluator(STORE, judge).preflight(req.corpus_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
    try:
        judge = _judge_for_request(req)
        return ProgressiveEvaluator(
            STORE,
            judge,
            reduction_batch_size=req.reduction_batch_size,
            max_workers=_effective_workers(req),
            retry_attempts=req.retry_attempts,
            retry_backoff_seconds=0.75,
            progress_callback=_evaluation_progress,
            cancellation_check=STORE.job_cancel_requested,
        ).evaluate(
            req.corpus_id,
            req.question,
            req.answer,
            order=req.order,
            job_id=req.job_id,
            resume=req.resume,
            max_blocks=req.max_blocks,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus/job not found") from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post("/benchmark")
def benchmark(req: BenchmarkRequest):
    try:
        judge = _judge_for_request(req)
        evaluator = ProgressiveEvaluator(
            STORE,
            judge,
            reduction_batch_size=req.reduction_batch_size,
            max_workers=_effective_workers(req),
            retry_attempts=req.retry_attempts,
        )
        return ScorePreservationBenchmark(
            evaluator, judge, max_direct_chars=req.max_direct_chars, tolerance=req.tolerance
        ).run(req.corpus_id, req.question, req.answer)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


# ---- Explorer ----------------------------------------------------------------
@app.get("/api/corpora/{corpus_id}/blocks")
def list_blocks(
    corpus_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    processable_only: bool = True,
):
    try:
        manifest = STORE.get_manifest(corpus_id)
        ids = manifest.coverage_ids() if processable_only else [*manifest.structural_block_ids, *manifest.coverage_ids()]
        page = ids[offset : offset + limit]
        return {"corpus_id": corpus_id, "offset": offset, "limit": limit, "total": len(ids), "blocks": STORE.get_blocks(corpus_id, page)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e


@app.get("/api/corpora/{corpus_id}/structure")
def corpus_structure(corpus_id: str):
    try:
        groups = build_explorer_groups(STORE, corpus_id)
        return {"corpus_id": corpus_id, "groups": groups}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e


@app.get("/api/corpora/{corpus_id}/search")
def search_blocks(corpus_id: str, q: str = Query(..., min_length=1), limit: int = Query(30, ge=1, le=200)):
    try:
        reader = CorpusReader(STORE, corpus_id)
        ids = reader.lexical_order(q)[:limit]
        return {
            "corpus_id": corpus_id, "query": q, "blocks": STORE.get_blocks(corpus_id, ids),
            "catalog": STORE.catalog_stats(corpus_id),
            "ranking_policy": "scheduling/navigation only; never coverage eligibility",
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus not found") from e


@app.get("/api/jobs/{corpus_id}/{job_id}")
def job_detail(corpus_id: str, job_id: str):
    try:
        manifest = STORE.get_manifest(corpus_id)
        cp = STORE.get_checkpoint(corpus_id, job_id)
        expected = set(manifest.coverage_ids())
        visited = expected & cp.state.visited
        failures = {k: v for k, v in cp.state.failures.items() if k in expected}
        return {
            "job_id": cp.job_id,
            "corpus_id": cp.corpus_id,
            "complete": cp.complete,
            "status": cp.status,
            "coverage": len(visited) / len(expected) if expected else 1.0,
            "visited": len(visited),
            "total": len(expected),
            "missing": [x for x in cp.ordered_block_ids if x in expected and x not in cp.state.visited][:200],
            "failures": failures,
            "evidence": cp.state.evidence,
            "evidence_atoms": sum(len(item.atoms) for item in cp.state.evidence),
            "evidence_kind_counts": evidence_kind_counts(cp.state.evidence),
            "reduction_nodes": cp.state.reduction_nodes,
            "question": cp.state.question,
            "answer": cp.state.answer,
            "score": cp.final_score,
            "rationale": cp.final_rationale,
            "usage": cp.state.usage,
            "ingest_coverage": manifest.ingest_coverage,
            "semantic_coverage": manifest.semantic_coverage,
            "ingest_ready": manifest.coverage_ready,
            "unresolved_units": manifest.unresolved_units,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="corpus/job not found") from e


@app.get("/corpora/{corpus_id}/blocks/{block_id}")
def read_block(corpus_id: str, block_id: str):
    try:
        return CorpusReader(STORE, corpus_id).read(block_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="block not found") from e


@app.get("/corpora/{corpus_id}/blocks/{block_id}/neighbors")
def block_neighbors(corpus_id: str, block_id: str):
    try:
        window = CorpusReader(STORE, corpus_id).neighbors(block_id)
        return {"previous": window.previous, "current": window.current, "next": window.next}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="block not found") from e


@app.get("/corpora/{corpus_id}/blocks/{block_id}/range")
def block_range(corpus_id: str, block_id: str, radius: int = Query(1, ge=0, le=20)):
    try:
        return CorpusReader(STORE, corpus_id).range(block_id, radius=radius)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="block not found") from e


# ---- Observability / admin ---------------------------------------------------
@app.get("/api/runtime/telemetry")
def runtime_telemetry():
    return collect_runtime_telemetry()


@app.get("/api/admin/overview")
def admin_overview():
    corpora = STORE.list_manifests()
    manifests = {m.corpus_id: m for m in corpora}
    jobs = STORE.list_checkpoints()
    ingest_jobs = STORE.list_ingest_jobs()
    routes = STORE.list_model_routes()
    job_rows: list[dict] = []
    failures: list[dict] = []
    pending_failures = 0

    for j in jobs:
        manifest = manifests.get(j.corpus_id)
        expected = set(manifest.coverage_ids()) if manifest else set(j.ordered_block_ids)
        visited = expected & j.state.visited
        coverage = len(visited) / len(expected) if expected else 1.0
        failed = {k: v for k, v in j.state.failures.items() if not expected or k in expected}
        pending_failures += len(failed)
        job_rows.append({
            "job_id": j.job_id,
            "corpus_id": j.corpus_id,
            "complete": j.complete,
            "status": j.status,
            "coverage": coverage,
            "visited": len(visited),
            "total": len(expected),
            "evidence": len(j.state.evidence),
            "failures": len(failed),
            "question": j.state.question,
            "inspection_attempts": sum(j.state.inspection_attempts.values()),
            "reduction_nodes": len(j.state.reduction_nodes),
            "score": j.final_score,
            "usage": j.state.usage.model_dump(),
            "ingest_coverage": manifest.ingest_coverage if manifest else 1.0,
            "semantic_coverage": manifest.semantic_coverage if manifest else 1.0,
            "ingest_ready": manifest.coverage_ready if manifest else True,
        })
        for block_id, error in failed.items():
            failures.append({"job_id": j.job_id, "corpus_id": j.corpus_id, "block_id": block_id, "error": error})

    telemetry = collect_runtime_telemetry()
    runtime = {
        "version": "0.13.0",
        "store": str(STORE.root),
        "default judge": "heuristic / model route / OpenAI-compatible",
        "Docling": "available" if importlib.util.find_spec("docling") else "optional, not installed",
        "RLM": "available" if importlib.util.find_spec("rlm") or importlib.util.find_spec("rlms") else "optional, not installed",
        "LMCache": "available" if importlib.util.find_spec("lmcache") else "serving-layer optional",
        "coverage policy": "ingest + semantic + execution coverage must all pass before final score",
        "ranking policy": "scheduling only; never filtering",
        "overflow policy": "exhaustive map + bounded hierarchical reduce + source rehydration",
        "block payload backend": getattr(STORE.block_store, "backend", STORE.block_backend),
        "job queue backend": "sqlite-wal",
        "active workers": len(QUEUE.workers()),
    }
    storage_rows: list[dict] = []
    for manifest in corpora:
        try:
            storage_rows.append(STORE.block_store_stats(manifest.corpus_id))
        except Exception:
            continue

    return {
        "metrics": {
            "corpora": len(corpora),
            "required_blocks": sum(x.required_blocks for x in corpora),
            "jobs": len(jobs),
            "ingest_jobs": len(ingest_jobs),
            "pending_failures": pending_failures,
            "total_bytes": sum(x.total_bytes for x in corpora),
            "prompt_tokens": sum(j.state.usage.prompt_tokens for j in jobs),
            "completion_tokens": sum(j.state.usage.completion_tokens for j in jobs),
            "estimated_cost_usd": sum(j.state.usage.estimated_cost_usd for j in jobs),
            "model_latency_seconds": sum(j.state.usage.latency_seconds for j in jobs),
            "coverage_ready_corpora": sum(1 for x in corpora if x.coverage_ready),
            "semantic_incomplete_corpora": sum(1 for x in corpora if not x.coverage_ready),
            "unresolved_units": sum(x.unresolved_units for x in corpora),
            "indexed_blocks": sum(STORE.catalog_stats(x.corpus_id).get("indexed_blocks", 0) for x in corpora),
            "stored_blocks": sum(int(x.get("stored_blocks", 0)) for x in storage_rows),
            "queue_depth": QUEUE.stats()["queued"],
            "active_workers": len(QUEUE.workers()),
        },
        "corpora": corpora,
        "ingest_jobs": ingest_jobs,
        "jobs": job_rows,
        "failures": failures,
        "routes": routes,
        "telemetry": telemetry,
        "runtime": runtime,
        "queue": {
            "stats": QUEUE.stats(),
            "workers": QUEUE.workers(),
            "jobs": [asdict(x) for x in QUEUE.list(limit=100)],
        },
    }
