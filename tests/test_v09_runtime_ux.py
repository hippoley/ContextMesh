from pathlib import Path

from fastapi.testclient import TestClient

from contextmesh.api import app
from contextmesh.events import EventBus
from contextmesh.ingest import ingest_paths
from contextmesh.judges import OpenAICompatibleJudge
from contextmesh.models import ContextBlock, Modality, SourceRef
from contextmesh.runtime import ProgressiveEvaluator
from contextmesh.store import FileContextStore


class RecordingJudge(OpenAICompatibleJudge):
    def __init__(self):
        super().__init__(
            model="fake",
            base_url="http://unused",
            max_context_tokens=2048,
            reserve_output_tokens=256,
            capabilities=["text", "table"],
        )
        self.prompts = []

    def _chat(self, messages):
        self.prompts.append(messages)
        # Works for inspect and reduction/finalization paths.
        text = str(messages)
        if "Produce strict JSON {score:number" in text:
            return '{"score": 88, "rationale": "ok"}'
        return '{"relevant": true, "note": "kept"}'


def test_route_aware_block_splitting_reads_oversized_block():
    judge = RecordingJudge()
    block = ContextBlock(
        id="b1",
        corpus_id="c1",
        modality=Modality.TEXT,
        text="needle " * 2000,
        source=SourceRef(asset_id="a1", path="big.txt"),
    )
    note, relevant = judge.inspect("verify needle", "candidate", block, [])
    assert relevant is True
    assert "route-aware slices=" in note
    # More than one model call proves the route context budget triggered paging.
    assert len(judge.prompts) > 1


def test_evaluation_can_cancel_and_resume_checkpoint(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    source = tmp_path / "doc.txt"
    source.write_text("alpha beta gamma\n" * 300, encoding="utf-8")
    manifest = ingest_paths([source], store, "corp_cancel", window_chars=500, overlap_chars=20)
    assert manifest.required_blocks > 1

    store.set_job_flag("corp_cancel", "job_cancel", cancel_requested=True)
    result = ProgressiveEvaluator(
        store,
        RecordingJudge(),
        cancellation_check=store.job_cancel_requested,
    ).evaluate("corp_cancel", "alpha?", "answer", job_id="job_cancel")
    assert result.complete is False
    assert result.score is None
    cp = store.get_checkpoint("corp_cancel", "job_cancel")
    assert cp.status == "cancelled"

    store.clear_job_flags("corp_cancel", "job_cancel")
    resumed = ProgressiveEvaluator(
        store,
        RecordingJudge(),
        cancellation_check=store.job_cancel_requested,
    ).evaluate("corp_cancel", "alpha?", "answer", job_id="job_cancel", resume=True)
    assert resumed.complete is True
    assert resumed.score == 88


def test_scoped_sse_filters_other_jobs():
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish("evaluation", {"job_id": "other", "corpus_id": "c"})
    bus.publish("evaluation", {"job_id": "wanted", "corpus_id": "c"})
    it = bus.iter_sse(sub, heartbeat_seconds=0.01, predicate=lambda x: x.get("job_id") == "wanted")
    assert "ready" in next(it)
    event = next(it)
    assert '"job_id": "wanted"' in event
    assert '"other"' not in event
    it.close()


def test_duplicate_upload_filenames_are_preserved_separately(tmp_path: Path, monkeypatch):
    # API globals are process-scoped; use the normal endpoint and assert manifest paths differ.
    client = TestClient(app)
    files = [
        ("files", ("same.txt", b"first needle", "text/plain")),
        ("files", ("same.txt", b"second needle", "text/plain")),
    ]
    r = client.post("/corpora", files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    names = [Path(x).name for x in data["assets"]]
    assert len(names) == 2
    assert len(set(names)) == 2

from contextmesh.judges import _parse_json_object
from contextmesh.models import EvaluationCheckpoint, EvaluationState, IngestJob, IngestStatus


def test_judge_json_parser_accepts_fenced_and_wrapped_json():
    assert _parse_json_object('```json\n{"score": 91, "rationale": "ok"}\n```')["score"] == 91
    assert _parse_json_object('Here is the result: {"relevant": true, "note": "needle"} thanks')["note"] == "needle"


def test_restart_reconciliation_marks_running_jobs_interrupted(tmp_path: Path):
    store = FileContextStore(tmp_path / "store")
    ingest = IngestJob(job_id="ing1", corpus_id="c1", total_files=1)
    ingest.status = IngestStatus.RUNNING
    store.put_ingest_job(ingest)
    cp = EvaluationCheckpoint(
        job_id="job1",
        corpus_id="c1",
        ordered_block_ids=[],
        state=EvaluationState(corpus_id="c1", question="q", answer="a"),
        status="running",
    )
    store.put_checkpoint(cp)
    result = store.reconcile_interrupted_jobs()
    assert result == {"ingest_jobs": 1, "evaluation_jobs": 1}
    assert store.get_ingest_job("ing1").status.value == "interrupted"
    assert store.get_checkpoint("c1", "job1").status == "interrupted"
