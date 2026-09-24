from __future__ import annotations

import asyncio
import json
import math
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, computed_field

from .models import BlockKind, ContextBlock, CorpusManifest, Modality, SourceRef, UsageMetrics
from .runtime import ProgressiveEvaluator
from .store import FileContextStore


class ProbeVerdict(str):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    MIXED = "mixed"
    UNSUPPORTED = "unsupported"


class ProbeDocument(BaseModel):
    id: str
    text: str
    decisive: bool = False
    stance: str = "neutral"
    roles: list[str] = Field(default_factory=list)


class ProbeScenario(BaseModel):
    id: str
    title: str
    description: str
    question: str
    candidate_answer: str
    expected_verdict: str
    documents: list[ProbeDocument]
    reality_sources: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def decisive_ids(self) -> list[str]:
        return [d.id for d in self.documents if d.decisive]

    @computed_field
    @property
    def exception_ids(self) -> list[str]:
        return [d.id for d in self.documents if d.decisive and "exception" in d.roles]

    @computed_field
    @property
    def contradiction_ids(self) -> list[str]:
        return [d.id for d in self.documents if d.decisive and "contradiction" in d.roles]


class ProbeSelection(BaseModel):
    backend: str
    selected_ids: list[str]
    ranked_ids: list[str] = Field(default_factory=list)
    latency_seconds: float = 0.0
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    note: str = ""


class EligibilityTraceItem(BaseModel):
    document_id: str
    rank: int | None = None
    selected: bool = False
    required: bool = True
    decisive: bool = False
    roles: list[str] = Field(default_factory=list)
    decision: str = ""
    reason: str = ""


class ProbeOutcome(BaseModel):
    scenario_id: str
    scenario_title: str
    backend: str
    selected_ids: list[str]
    ranked_ids: list[str]
    total_documents: int
    selected_documents: int
    coverage: float
    decisive_total: int
    decisive_found: int
    decisive_recall: float | None
    first_decisive_rank: int | None
    expected_verdict: str
    evidence_available_verdict: str
    verdict_correct: bool
    exception_preserved: bool | None
    contradiction_preserved: bool | None
    source_traceable: bool
    forced_context_when_unsupported: bool
    latency_seconds: float
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    live_verdict: str | None = None
    live_verdict_correct: bool | None = None
    live_source_ids: list[str] = Field(default_factory=list)
    eligibility_trace: list[EligibilityTraceItem] = Field(default_factory=list)
    note: str = ""


class RealityProbeReport(BaseModel):
    top_k: int
    outcomes: list[ProbeOutcome]
    live_judge: bool = False

    @computed_field
    @property
    def by_backend(self) -> dict[str, dict[str, float | int]]:
        out: dict[str, dict[str, float | int]] = {}
        names = sorted({x.backend for x in self.outcomes})
        for name in names:
            rows = [x for x in self.outcomes if x.backend == name]
            recall_rows = [x.decisive_recall for x in rows if x.decisive_recall is not None]
            out[name] = {
                "scenarios": len(rows),
                "verdict_correct": sum(1 for x in rows if x.verdict_correct),
                "mean_decisive_recall": (
                    sum(float(x) for x in recall_rows) / len(recall_rows) if recall_rows else 1.0
                ),
                "full_coverage_runs": sum(1 for x in rows if math.isclose(x.coverage, 1.0)),
                "forced_context_on_unsupported": sum(
                    1 for x in rows if x.forced_context_when_unsupported
                ),
            }
            live_rows = [x for x in rows if x.live_verdict_correct is not None]
            if live_rows:
                out[name]["live_verdict_correct"] = sum(
                    1 for x in live_rows if x.live_verdict_correct
                )
        return out

    def to_markdown(self) -> str:
        lines = [
            "# ContextMesh Reality Probe",
            "",
            f"top_k = {self.top_k}",
            "",
            "| Scenario | Backend | Coverage | Decisive recall | First decisive rank | Evidence verdict | Expected | Correct |",
            "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
        ]
        for x in self.outcomes:
            recall = "n/a" if x.decisive_recall is None else f"{x.decisive_recall:.0%}"
            lines.append(
                f"| {x.scenario_id} | {x.backend} | {x.coverage:.0%} | {recall} | "
                f"{x.first_decisive_rank if x.first_decisive_rank is not None else 'n/a'} | "
                f"{x.evidence_available_verdict} | {x.expected_verdict} | "
                f"{'yes' if x.verdict_correct else 'no'} |"
            )
        lines.extend(["", "## Decisive eligibility trace", ""])
        for x in self.outcomes:
            decisive = [t for t in x.eligibility_trace if t.decisive]
            for item in decisive:
                rank = item.rank if item.rank is not None else "n/a"
                lines.append(
                    f"- {x.scenario_id} / {x.backend}: {item.document_id} "
                    f"rank={rank}, selected={'yes' if item.selected else 'no'}, "
                    f"decision={item.decision} — {item.reason}"
                )
        lines.extend(["", "## Aggregate", "", "JSON:", json.dumps(self.by_backend, indent=2)])
        return "\n".join(lines)


class ProbeBackend(Protocol):
    name: str

    def select(self, scenario: ProbeScenario) -> ProbeSelection: ...


_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_DOC_MARKER_RE = re.compile(r"CM_DOC_ID::([A-Za-z0-9_.:-]+)")


def _tokens(text: str) -> set[str]:
    return {x.lower() for x in _TOKEN_RE.findall(text or "") if len(x) > 1}


def _lexical_rank(scenario: ProbeScenario) -> list[str]:
    query = _tokens(scenario.question)
    scored: list[tuple[float, int, str]] = []
    for i, doc in enumerate(scenario.documents):
        terms = _tokens(doc.text)
        overlap = len(query & terms)
        score = overlap / max(1.0, math.sqrt(len(query) * max(1, len(terms))))
        scored.append((score, -i, doc.id))
    scored.sort(reverse=True)
    return [doc_id for _, _, doc_id in scored]


class LexicalTopKBackend:
    name = "lexical-topk"

    def __init__(self, top_k: int = 5):
        self.top_k = max(1, int(top_k))

    def select(self, scenario: ProbeScenario) -> ProbeSelection:
        started = time.perf_counter()
        ranked = _lexical_rank(scenario)
        return ProbeSelection(
            backend=self.name,
            selected_ids=ranked[: self.top_k],
            ranked_ids=ranked,
            latency_seconds=time.perf_counter() - started,
            note="Deterministic lexical control. It is a mechanism baseline, not a claim about Cognee.",
        )


class _CoverageProbeJudge:
    def can_inspect(self, block: ContextBlock) -> bool:
        return True

    def inspect(self, question: str, answer: str, block: ContextBlock, notes: list[str]):
        return f"{block.id}: probe inspected", True

    def reduce_notes(self, question: str, answer: str, notes: list[str], level: int) -> str:
        return f"L{level}: " + ",".join(x.split(":", 1)[0] for x in notes)

    def finalize(self, state):
        return 100.0, "Reality probe coverage execution completed."

    def usage_snapshot(self) -> UsageMetrics:
        return UsageMetrics()


def _materialize_scenario(store: FileContextStore, scenario: ProbeScenario, corpus_id: str) -> None:
    blocks: list[ContextBlock] = []
    total_chars = 0
    for index, doc in enumerate(scenario.documents):
        block = ContextBlock(
            id=doc.id,
            corpus_id=corpus_id,
            modality=Modality.TEXT,
            kind=BlockKind.CONTENT,
            text=doc.text,
            source=SourceRef(
                asset_id=f"probe:{scenario.id}",
                path=f"probe://{scenario.id}/{doc.id}",
                locator={"document_index": index},
            ),
            processable=True,
            metadata={
                "probe_decisive": doc.decisive,
                "probe_stance": doc.stance,
                "probe_roles": doc.roles,
            },
        )
        blocks.append(block)
        total_chars += len(doc.text)
    store.put_blocks(blocks)
    store.put_manifest(
        CorpusManifest(
            schema_version="0.15-probe",
            corpus_id=corpus_id,
            assets=[f"probe://{scenario.id}"],
            block_ids=[x.id for x in blocks],
            required_block_ids=[x.id for x in blocks],
            total_blocks=len(blocks),
            required_blocks=len(blocks),
            total_chars=total_chars,
            modality_counts={"text": len(blocks)},
            required_capabilities=["text"],
        )
    )


class ContextMeshFullCoverageBackend:
    name = "contextmesh-full-coverage"

    def __init__(self, *, workers: int = 4):
        self.workers = max(1, int(workers))

    def select(self, scenario: ProbeScenario) -> ProbeSelection:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="contextmesh-reality-probe-") as td:
            store = FileContextStore(Path(td) / "store")
            corpus_id = f"probe_{scenario.id}_{uuid.uuid4().hex[:8]}"
            _materialize_scenario(store, scenario, corpus_id)
            ranked = _lexical_rank(scenario)
            result = ProgressiveEvaluator(
                store,
                _CoverageProbeJudge(),
                max_workers=self.workers,
                execution_batch_size=max(4, self.workers * 2),
                reduction_batch_size=16,
            ).evaluate(
                corpus_id,
                scenario.question,
                scenario.candidate_answer,
                order=ranked,
            )
            if not result.complete or result.coverage < 1.0:
                raise RuntimeError(
                    f"ContextMesh probe failed coverage invariant: complete={result.complete} "
                    f"coverage={result.coverage}"
                )
            selected = [x.block_id for x in result.evidence]
            return ProbeSelection(
                backend=self.name,
                selected_ids=selected,
                ranked_ids=ranked,
                latency_seconds=time.perf_counter() - started,
                usage=result.usage,
                note=(
                    "Actual ProgressiveEvaluator run. Lexical ranking scheduled reading order; "
                    "all required documents remained eligible and were visited."
                ),
            )


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk_strings(item)
        return
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            yield from _walk_strings(dump(mode="json"))
            return
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            yield from _walk_strings(vars(value))
        except Exception:
            return


def extract_document_markers(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for text in _walk_strings(value):
        for match in _DOC_MARKER_RE.finditer(text):
            doc_id = match.group(1)
            if doc_id not in seen:
                seen.add(doc_id)
                out.append(doc_id)
    return out


class CogneeChunksBackend:
    name = "cognee-chunks"

    def __init__(
        self,
        top_k: int = 5,
        *,
        fetch_k: int | None = None,
        dataset_prefix: str = "contextmesh_reality_probe",
        extractor: str | None = None,
    ):
        self.top_k = max(1, int(top_k))
        self.fetch_k = max(self.top_k, int(fetch_k or self.top_k))
        self.dataset_prefix = dataset_prefix
        self.extractor = extractor

    async def _select_async(self, scenario: ProbeScenario) -> ProbeSelection:
        try:
            import cognee
            from cognee.modules.search.types import SearchType
        except ImportError as exc:
            raise RuntimeError(
                "Cognee backend is optional. Install with pip install -e '.[cognee]'."
            ) from exc

        dataset = f"{self.dataset_prefix}_{scenario.id}_{uuid.uuid4().hex[:8]}"
        payloads = [f"CM_DOC_ID::{doc.id}\n{doc.text}" for doc in scenario.documents]
        remember_kwargs: dict[str, Any] = {"self_improvement": False}
        if self.extractor:
            remember_kwargs["extractor"] = self.extractor

        started = time.perf_counter()
        remembered = await cognee.remember(payloads, dataset_name=dataset, **remember_kwargs)
        if getattr(remembered, "status", None) == "errored":
            raise RuntimeError(f"Cognee remember failed: {getattr(remembered, 'error', None)}")

        results = await cognee.search(
            scenario.question,
            query_type=SearchType.CHUNKS,
            datasets=[dataset],
            top_k=self.fetch_k,
        )
        ranked = extract_document_markers(results)
        return ProbeSelection(
            backend=self.name,
            selected_ids=ranked[: self.top_k],
            ranked_ids=ranked,
            latency_seconds=time.perf_counter() - started,
            note=(
                f"Live Cognee SearchType.CHUNKS dataset={dataset}; decision_top_k={self.top_k}, "
                f"fetch_k={self.fetch_k}. Probe source markers map returned short chunks back to benchmark IDs."
            ),
        )

    def select(self, scenario: ProbeScenario) -> ProbeSelection:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._select_async(scenario))
        raise RuntimeError("CogneeChunksBackend.select() must be called outside an active asyncio loop")


class LiveProbeVerdictJudge:
    def __init__(self, openai_compatible_judge: Any):
        self.judge = openai_compatible_judge

    def judge(self, scenario: ProbeScenario, selected_docs: list[ProbeDocument]) -> tuple[str, list[str]]:
        evidence = "\n\n".join(f"[SOURCE {d.id}] {d.text}" for d in selected_docs)
        prompt = f"""You are evaluating whether a candidate answer is supported by the supplied evidence.
Return JSON only:
{{"verdict":"supports|contradicts|mixed|unsupported","source_ids":["..."]}}

Question: {scenario.question}
Candidate answer: {scenario.candidate_answer}

Evidence:
{evidence}

Rules:
- Use only supplied evidence.
- If the evidence is insufficient, verdict=unsupported.
- If evidence directly conflicts with the candidate answer, verdict=contradicts.
- If both materially supporting and conflicting evidence exist, verdict=mixed.
"""
        raw = self.judge._chat([{"role": "user", "content": [{"type": "text", "text": prompt}]}])
        from .judges import _parse_json_object

        obj = _parse_json_object(raw)
        if not obj:
            raise ValueError(f"live probe judge returned non-JSON content: {raw[:240]}")
        verdict = str(obj.get("verdict") or "").strip().lower()
        if verdict not in {
            ProbeVerdict.SUPPORTS,
            ProbeVerdict.CONTRADICTS,
            ProbeVerdict.MIXED,
            ProbeVerdict.UNSUPPORTED,
        }:
            raise ValueError(f"invalid live probe verdict: {verdict}")
        ids = [str(x) for x in (obj.get("source_ids") or [])]
        return verdict, ids


def _available_verdict(scenario: ProbeScenario, selected_ids: set[str]) -> str:
    stances = {
        doc.stance
        for doc in scenario.documents
        if doc.decisive and doc.id in selected_ids and doc.stance in {"support", "contradict"}
    }
    if stances == {"support", "contradict"}:
        return ProbeVerdict.MIXED
    if "contradict" in stances:
        return ProbeVerdict.CONTRADICTS
    if "support" in stances:
        return ProbeVerdict.SUPPORTS
    return ProbeVerdict.UNSUPPORTED


def _preserved(required_ids: list[str], selected: set[str]) -> bool | None:
    if not required_ids:
        return None
    return set(required_ids).issubset(selected)


def evaluate_selection(
    scenario: ProbeScenario,
    selection: ProbeSelection,
    *,
    live_judge: LiveProbeVerdictJudge | None = None,
) -> ProbeOutcome:
    selected = set(selection.selected_ids)
    decisive = set(scenario.decisive_ids)
    found = decisive & selected
    recall = len(found) / len(decisive) if decisive else None
    ranks = {doc_id: index + 1 for index, doc_id in enumerate(selection.ranked_ids)}
    decisive_ranks = [ranks[x] for x in decisive if x in ranks]
    available = _available_verdict(scenario, selected)

    known_ids = {x.id for x in scenario.documents}
    by_doc = {x.id: x for x in scenario.documents}
    trace: list[EligibilityTraceItem] = []
    for doc in scenario.documents:
        rank = ranks.get(doc.id)
        is_selected = doc.id in selected
        if is_selected:
            decision = "selected"
            reason = "backend exposed this source to downstream evidence"
        elif rank is not None:
            decision = "excluded"
            reason = f"rank {rank} fell outside backend visible eligibility"
        else:
            decision = "unranked"
            reason = "backend did not expose this source in the measured ranking"
        if selection.backend == "contextmesh-full-coverage":
            decision = "required-and-visited" if is_selected else "required-missing"
            reason = (
                "manifest-required source remained eligible regardless of rank"
                if is_selected else
                "manifest-required source was not visited; this violates the probe invariant"
            )
        trace.append(EligibilityTraceItem(
            document_id=doc.id,
            rank=rank,
            selected=is_selected,
            required=True,
            decisive=doc.decisive,
            roles=list(doc.roles),
            decision=decision,
            reason=reason,
        ))

    live_verdict = None
    live_sources: list[str] = []
    live_correct = None
    if live_judge is not None:
        by_id = {x.id: x for x in scenario.documents}
        docs = [by_id[x] for x in selection.selected_ids if x in by_id]
        live_verdict, live_sources = live_judge.judge(scenario, docs)
        live_correct = live_verdict == scenario.expected_verdict

    return ProbeOutcome(
        scenario_id=scenario.id,
        scenario_title=scenario.title,
        backend=selection.backend,
        selected_ids=selection.selected_ids,
        ranked_ids=selection.ranked_ids,
        total_documents=len(scenario.documents),
        selected_documents=len(selection.selected_ids),
        coverage=len(selected & known_ids) / len(known_ids) if known_ids else 1.0,
        decisive_total=len(decisive),
        decisive_found=len(found),
        decisive_recall=recall,
        first_decisive_rank=min(decisive_ranks) if decisive_ranks else None,
        expected_verdict=scenario.expected_verdict,
        evidence_available_verdict=available,
        verdict_correct=available == scenario.expected_verdict,
        exception_preserved=_preserved(scenario.exception_ids, selected),
        contradiction_preserved=_preserved(scenario.contradiction_ids, selected),
        source_traceable=all(x in known_ids for x in selection.selected_ids),
        forced_context_when_unsupported=(
            scenario.expected_verdict == ProbeVerdict.UNSUPPORTED
            and bool(selection.selected_ids)
            and not scenario.decisive_ids
        ),
        latency_seconds=selection.latency_seconds,
        usage=selection.usage,
        live_verdict=live_verdict,
        live_verdict_correct=live_correct,
        live_source_ids=live_sources,
        eligibility_trace=trace,
        note=selection.note,
    )


def issue_derived_scenarios(*, crowding: int = 24) -> list[ProbeScenario]:
    crowding = max(8, int(crowding))

    transfer_distractors = [
        ProbeDocument(
            id=f"transfer-general-{i:02d}",
            text=(
                "Standard outbound wire transfer policy. Active customer accounts may submit "
                "wire transfers through the payments service after ordinary balance and routing checks. "
                f"Control example {i:02d}."
            ),
        )
        for i in range(crowding)
    ]
    rare_exception = ProbeScenario(
        id="rare-exception",
        title="Rare exception outside the obvious vocabulary",
        description="A low-overlap appendix changes the answer to a high-overlap general rule.",
        question="Can an account under a freeze execute an outbound wire transfer?",
        candidate_answer="Yes. The transfer can proceed after the ordinary checks.",
        expected_verdict=ProbeVerdict.CONTRADICTS,
        documents=[
            *transfer_distractors,
            ProbeDocument(
                id="transfer-legal-hold",
                text=(
                    "Appendix H — legal-hold handling. A legal hold disables every external "
                    "disbursement rail. No value may leave the held ledger until compliance releases it."
                ),
                decisive=True,
                stance="contradict",
                roles=["exception"],
            ),
        ],
        reality_sources=[
            "https://github.com/topoteretes/cognee/issues/3706",
            "https://github.com/topoteretes/cognee/issues/4462",
        ],
    )

    export_distractors = [
        ProbeDocument(
            id=f"export-old-{i:02d}",
            text=(
                "Regional export handbook: controlled analytics packages may be shipped to Red Region "
                "customers after the normal export review and customer screening. "
                f"Legacy handbook example {i:02d}."
            ),
            stance="support",
        )
        for i in range(crowding)
    ]
    contradiction = ProbeScenario(
        id="later-contradiction",
        title="Later bulletin overrides many old matching passages",
        description="Many older passages support the answer; one later bulletin reverses it.",
        question="May we ship the analytics package to a Red Region customer?",
        candidate_answer="Yes, after normal export review.",
        expected_verdict=ProbeVerdict.CONTRADICTS,
        documents=[
            *export_distractors,
            ProbeDocument(
                id="export-2026-bulletin",
                text=(
                    "Compliance bulletin, effective 2026-09-01: destination class R is now embargoed. "
                    "All outbound delivery of analytics software to that destination class is prohibited, "
                    "including requests that previously passed standard review."
                ),
                decisive=True,
                stance="contradict",
                roles=["contradiction", "date"],
            ),
        ],
        reality_sources=[
            "https://github.com/topoteretes/cognee/issues/4296",
            "https://github.com/topoteretes/cognee/issues/3805",
        ],
    )

    templated = [
        ProbeDocument(
            id=f"telemetry-{i:02d}",
            text=(
                '{"service":"atlas","deployment":"prod","gate":"release","state":"approved",'
                f'"sample":{i},"message":"release gate completed successfully"}}'
            ),
            stance="support",
        )
        for i in range(crowding)
    ]
    near_duplicate = ProbeScenario(
        id="near-duplicate-crowding",
        title="Templated near-duplicates consume visible slots",
        description="Structured near-duplicates crowd the ranking while a differently worded exception matters.",
        question="Is the Atlas production release approved to proceed?",
        candidate_answer="Yes. The release is approved to proceed.",
        expected_verdict=ProbeVerdict.CONTRADICTS,
        documents=[
            *templated,
            ProbeDocument(
                id="atlas-manual-stop",
                text=(
                    "Change-control note: deployment Atlas has been placed in manual STOP state by the "
                    "risk desk. Promotion is blocked until incident R-774 is cleared."
                ),
                decisive=True,
                stance="contradict",
                roles=["exception", "contradiction"],
            ),
        ],
        reality_sources=["https://github.com/topoteretes/cognee/issues/3706"],
    )

    unsupported = ProbeScenario(
        id="unsupported-query",
        title="No corpus support",
        description="The corpus is non-empty but contains no evidence about the question.",
        question="What is the optimal breeding cycle of Antarctic emperor penguins?",
        candidate_answer="The optimal breeding cycle is nine months.",
        expected_verdict=ProbeVerdict.UNSUPPORTED,
        documents=[
            ProbeDocument(
                id=f"technical-{i:02d}",
                text=(
                    "Production operations note covering Linux package rollout, database backup, "
                    f"and container health check sample {i:02d}."
                ),
            )
            for i in range(max(8, crowding // 2))
        ],
        reality_sources=["https://github.com/topoteretes/cognee/issues/4462"],
    )
    return [rare_exception, contradiction, near_duplicate, unsupported]


def run_reality_probe_suite(
    *,
    top_k: int = 5,
    backends: list[ProbeBackend] | None = None,
    scenarios: list[ProbeScenario] | None = None,
    live_judge: LiveProbeVerdictJudge | None = None,
) -> RealityProbeReport:
    scenarios = scenarios or issue_derived_scenarios()
    backends = backends or [LexicalTopKBackend(top_k), ContextMeshFullCoverageBackend()]
    outcomes: list[ProbeOutcome] = []
    for scenario in scenarios:
        for backend in backends:
            outcomes.append(
                evaluate_selection(scenario, backend.select(scenario), live_judge=live_judge)
            )
    return RealityProbeReport(top_k=top_k, outcomes=outcomes, live_judge=live_judge is not None)
