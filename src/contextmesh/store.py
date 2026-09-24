from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from pathlib import Path

from .catalog import SQLiteContextCatalog
from .blockstore import JsonBlockPayloadStore, SQLiteBlockPayloadStore
from .models import ContextBlock, CorpusManifest, EvaluationCheckpoint, IngestJob, IngestStatus, ModelRoute


class FileContextStore:
    """Portable filesystem store.

    Corpus data is model-agnostic. Model-specific KV/prefix caches stay below the
    serving layer. v0.7 adds durable ingest jobs and model-route configuration.
    """

    def __init__(self, root: str | Path, *, block_backend: str | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "_control").mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.catalog = SQLiteContextCatalog(self.root / "_catalog.sqlite3")
        requested_backend = (block_backend or os.getenv("CONTEXTMESH_BLOCK_BACKEND", "sqlite")).strip().lower()
        if requested_backend in {"sqlite", "sqlite-payload", "auto"}:
            self.block_store = SQLiteBlockPayloadStore(self.root / "_blocks.sqlite3")
            self.block_backend = "sqlite"
        elif requested_backend in {"json", "json-files", "filesystem"}:
            self.block_store = JsonBlockPayloadStore(self.root)
            self.block_backend = "json"
        else:
            raise ValueError(f"unsupported ContextMesh block backend: {requested_backend}")
        # Always keep a legacy JSON reader available so v0.1-v0.11 corpora can be
        # opened and lazily migrated after upgrading to the SQLite runtime backend.
        self._legacy_blocks = JsonBlockPayloadStore(self.root)


    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _corpus_dir(self, corpus_id: str, *, create: bool = True) -> Path:
        p = self.root / corpus_id
        if create:
            p.mkdir(parents=True, exist_ok=True)
        return p

    def put_block(self, block: ContextBlock) -> None:
        self.put_blocks([block])

    def put_blocks(self, blocks: list[ContextBlock]) -> None:
        if not blocks:
            return
        # One batch write for payloads + one batch write for catalog metadata.
        # SQLite mode avoids the millions-of-small-files bottleneck while preserving
        # the manifest as the authoritative coverage contract.
        self.block_store.put_many(blocks)
        self.catalog.upsert_many(blocks)

    def get_block(self, corpus_id: str, block_id: str) -> ContextBlock:
        try:
            return self.block_store.get(corpus_id, block_id)
        except FileNotFoundError:
            if self.block_backend != "sqlite":
                raise
            # Backwards compatibility: v0.1-v0.11 stored one JSON file per block.
            # Read it once, then lazily migrate it into the SQLite payload backend.
            block = self._legacy_blocks.get(corpus_id, block_id)
            self.block_store.put_many([block])
            return block

    def get_blocks(self, corpus_id: str, block_ids: list[str]) -> list[ContextBlock]:
        if not block_ids:
            return []
        found = {b.id: b for b in self.block_store.get_many(corpus_id, block_ids)}
        if len(found) < len(set(block_ids)) and self.block_backend == "sqlite":
            missing = [x for x in block_ids if x not in found]
            legacy = self._legacy_blocks.get_many(corpus_id, missing)
            if legacy:
                self.block_store.put_many(legacy)
                found.update({b.id: b for b in legacy})
        return [found[x] for x in block_ids if x in found]

    def put_manifest(self, manifest: CorpusManifest) -> None:
        p = self._corpus_dir(manifest.corpus_id) / "manifest.json"
        self._atomic_write(p, manifest.model_dump_json(indent=2))

    def get_manifest(self, corpus_id: str) -> CorpusManifest:
        p = self._corpus_dir(corpus_id, create=False) / "manifest.json"
        return CorpusManifest.model_validate_json(p.read_text(encoding="utf-8"))

    def list_manifests(self) -> list[CorpusManifest]:
        out: list[CorpusManifest] = []
        if not self.root.exists():
            return out
        for p in sorted(self.root.glob("*/manifest.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.parent.name.startswith("_"):
                continue
            try:
                out.append(CorpusManifest.model_validate_json(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def delete_corpus(self, corpus_id: str) -> bool:
        p = self._corpus_dir(corpus_id, create=False)
        if not p.exists():
            return False
        shutil.rmtree(p)
        self.catalog.delete_corpus(corpus_id)
        self.block_store.delete_corpus(corpus_id)
        return True

    def ensure_block_store(self, corpus_id: str) -> dict:
        """Ensure the configured payload backend can serve every addressable block.

        When upgrading an older JSON-per-block corpus into SQLite mode, missing
        payloads are migrated in deterministic batches. No coverage IDs are changed.
        """
        manifest = self.get_manifest(corpus_id)
        expected_ids = list(dict.fromkeys([*manifest.structural_block_ids, *manifest.block_ids]))
        stored_before = self.block_store.count(corpus_id)
        migrated = 0
        if self.block_backend == "sqlite" and stored_before < len(expected_ids):
            existing = self.block_store.existing_ids(corpus_id, expected_ids)
            missing = [x for x in expected_ids if x not in existing]
            for start in range(0, len(missing), 1000):
                legacy = self._legacy_blocks.get_many(corpus_id, missing[start:start + 1000])
                if legacy:
                    migrated += self.block_store.put_many(legacy)
        stored = self.block_store.count(corpus_id)
        legacy = self._legacy_blocks.count(corpus_id)
        base = self.block_store.stats(corpus_id) if hasattr(self.block_store, "stats") else {
            "backend": getattr(self.block_store, "backend", self.block_backend),
            "stored_blocks": stored,
        }
        base.update({
            "configured_backend": self.block_backend,
            "addressable_manifest_blocks": len(expected_ids),
            "legacy_json_blocks": legacy,
            "migrated_blocks": migrated,
            "ready": stored >= len(expected_ids),
            "policy": "payload storage only; manifest remains coverage authority",
        })
        return base

    def block_store_stats(self, corpus_id: str) -> dict:
        return self.ensure_block_store(corpus_id)

    def ensure_catalog(self, corpus_id: str) -> dict:
        """Backfill the SQLite catalog for corpora created by older ContextMesh versions."""
        manifest = self.get_manifest(corpus_id)
        expected_ids = list(dict.fromkeys([*manifest.structural_block_ids, *manifest.block_ids]))
        indexed_before = self.catalog.count(corpus_id)
        if indexed_before < len(expected_ids):
            # Ensure old payloads are migrated first, then batch catalog writes instead
            # of opening one SQLite transaction per block.
            self.ensure_block_store(corpus_id)
            for start in range(0, len(expected_ids), 1000):
                blocks = self.get_blocks(corpus_id, expected_ids[start:start + 1000])
                if blocks:
                    self.catalog.upsert_many(blocks)
        stats = self.catalog.stats(corpus_id)
        stats["manifest_blocks"] = manifest.total_blocks
        stats["manifest_required_blocks"] = manifest.required_blocks
        stats["addressable_manifest_blocks"] = len(expected_ids)
        stats["ready"] = (
            stats["indexed_blocks"] >= len(expected_ids)
            and stats["processable_blocks"] >= manifest.required_blocks
        )
        return stats

    def search_blocks(self, corpus_id: str, query: str, *, limit: int = 100) -> list[str]:
        self.ensure_catalog(corpus_id)
        return self.catalog.search(corpus_id, query, limit=limit, processable_only=True)

    def catalog_stats(self, corpus_id: str) -> dict:
        return self.ensure_catalog(corpus_id)

    def put_checkpoint(self, checkpoint: EvaluationCheckpoint) -> None:
        d = self._corpus_dir(checkpoint.corpus_id) / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        self._atomic_write(d / f"{checkpoint.job_id}.json", checkpoint.model_dump_json(indent=2))

    def get_checkpoint(self, corpus_id: str, job_id: str) -> EvaluationCheckpoint:
        p = self._corpus_dir(corpus_id, create=False) / "jobs" / f"{job_id}.json"
        return EvaluationCheckpoint.model_validate_json(p.read_text(encoding="utf-8"))

    def list_checkpoints(self, corpus_id: str | None = None) -> list[EvaluationCheckpoint]:
        paths: list[Path]
        if corpus_id:
            paths = list((self._corpus_dir(corpus_id, create=False) / "jobs").glob("*.json"))
        else:
            paths = list(self.root.glob("*/jobs/*.json"))
        paths = sorted((p for p in paths if p.is_file()), key=lambda x: x.stat().st_mtime, reverse=True)
        out: list[EvaluationCheckpoint] = []
        for p in paths:
            try:
                out.append(EvaluationCheckpoint.model_validate_json(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out


    # ---- Durable job control --------------------------------------------------
    def _job_control_path(self, corpus_id: str, job_id: str) -> Path:
        return self.root / "_control" / "job_flags" / corpus_id / f"{job_id}.json"

    def set_job_flag(self, corpus_id: str, job_id: str, *, cancel_requested: bool | None = None) -> dict:
        p = self._job_control_path(corpus_id, job_id)
        with self._lock:
            data = {}
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            if cancel_requested is not None:
                data["cancel_requested"] = bool(cancel_requested)
            self._atomic_write(p, json.dumps(data, indent=2, ensure_ascii=False))
        return data

    def job_cancel_requested(self, corpus_id: str, job_id: str) -> bool:
        p = self._job_control_path(corpus_id, job_id)
        if not p.exists():
            return False
        try:
            return bool(json.loads(p.read_text(encoding="utf-8")).get("cancel_requested"))
        except Exception:
            return False

    def clear_job_flags(self, corpus_id: str, job_id: str) -> None:
        p = self._job_control_path(corpus_id, job_id)
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    def reconcile_interrupted_jobs(self) -> dict[str, int]:
        """Mark in-process work left behind by a previous server process as resumable."""
        ingest_count = 0
        eval_count = 0
        for job in self.list_ingest_jobs():
            if job.status.value in {"queued", "running"}:
                job.status = IngestStatus.INTERRUPTED
                job.message = "Interrupted by server restart; retry is available."
                self.put_ingest_job(job)
                ingest_count += 1
        for cp in self.list_checkpoints():
            if cp.status in {"queued", "running", "cancelling"}:
                cp.status = "interrupted"
                cp.final_rationale = "Interrupted by server restart; checkpoint can be resumed."
                self.put_checkpoint(cp)
                eval_count += 1
        return {"ingest_jobs": ingest_count, "evaluation_jobs": eval_count}

    # ---- Ingest control plane -------------------------------------------------
    def put_ingest_job(self, job: IngestJob) -> None:
        d = self.root / "_control" / "ingest"
        d.mkdir(parents=True, exist_ok=True)
        self._atomic_write(d / f"{job.job_id}.json", job.model_dump_json(indent=2))

    def get_ingest_job(self, job_id: str) -> IngestJob:
        p = self.root / "_control" / "ingest" / f"{job_id}.json"
        return IngestJob.model_validate_json(p.read_text(encoding="utf-8"))

    def list_ingest_jobs(self) -> list[IngestJob]:
        d = self.root / "_control" / "ingest"
        if not d.exists():
            return []
        out: list[IngestJob] = []
        for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                out.append(IngestJob.model_validate_json(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    # ---- Model routing --------------------------------------------------------
    def _routes_path(self) -> Path:
        return self.root / "_control" / "model_routes.json"

    def list_model_routes(self) -> list[ModelRoute]:
        p = self._routes_path()
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return [ModelRoute.model_validate(x) for x in data]
        except Exception:
            return []

    def put_model_routes(self, routes: list[ModelRoute]) -> None:
        with self._lock:
            self._atomic_write(self._routes_path(), json.dumps([r.model_dump() for r in routes], indent=2, ensure_ascii=False))

    def upsert_model_route(self, route: ModelRoute) -> ModelRoute:
        routes = self.list_model_routes()
        by_id = {x.id: x for x in routes}
        by_id[route.id] = route
        self.put_model_routes(list(by_id.values()))
        return route

    def delete_model_route(self, route_id: str) -> bool:
        routes = self.list_model_routes()
        new = [x for x in routes if x.id != route_id]
        if len(new) == len(routes):
            return False
        self.put_model_routes(new)
        return True
