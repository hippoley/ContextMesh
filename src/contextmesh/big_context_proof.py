from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from pydantic import BaseModel, Field

from .models import ContextBlock, CorpusManifest, Modality, UsageMetrics
from .reader import CorpusReader
from .runtime import ProgressiveEvaluator
from .semantics import ExecutionContract
from .store import FileContextStore
from .token_budget import TextTokenBudget


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    NOT_RUN = "not-run"


class ProofGate(BaseModel):
    gate: int
    name: str
    status: GateStatus
    blockers: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


def _format_family(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".txt", ".md", ".rst", ".html", ".xml", ".yaml", ".yml", ".json"}:
        return "text"
    if suffix in {".csv", ".xlsx", ".xls", ".ods"}:
        return "table"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".docx", ".doc"}:
        return "document"
    if suffix in {".pptx", ".ppt", ".odp"}:
        return "slides"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tiff", ".bmp"}:
        return "image"
    if suffix in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}:
        return "audio"
    if suffix in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
        return "video"
    return suffix.lstrip(".") or "unknown"


class Gate1CorpusSpec(BaseModel):
    min_assets: int = 10
    max_assets: int = 30
    min_format_families: int = 3
    min_corpus_to_context_ratio: float = 5.0
    model_context_tokens: int
    require_source_hashes: bool = True
    require_semantic_ready: bool = True


class Gate1CorpusReport(BaseModel):
    gate: int = 1
    status: GateStatus
    corpus_id: str
    assets: int
    required_blocks: int
    total_bytes: int
    total_chars: int
    estimated_tokens: int
    model_context_tokens: int
    corpus_to_context_ratio: float
    format_families: dict[str, int]
    modalities: dict[str, int]
    source_hash_coverage: float
    ingest_coverage: float
    semantic_coverage: float
    coverage_ready: bool
    blockers: list[str] = Field(default_factory=list)

    def as_gate(self) -> ProofGate:
        return ProofGate(
            gate=1,
            name="Corpus Reality Gate",
            status=self.status,
            blockers=self.blockers,
            metrics={
                "assets": self.assets,
                "required_blocks": self.required_blocks,
                "estimated_tokens": self.estimated_tokens,
                "model_context_tokens": self.model_context_tokens,
                "corpus_to_context_ratio": self.corpus_to_context_ratio,
                "format_families": self.format_families,
                "modalities": self.modalities,
                "source_hash_coverage": self.source_hash_coverage,
                "ingest_coverage": self.ingest_coverage,
                "semantic_coverage": self.semantic_coverage,
            },
        )


def evaluate_gate1_corpus(
    manifest: CorpusManifest,
    spec: Gate1CorpusSpec,
    *,
    token_budget: TextTokenBudget | None = None,
) -> Gate1CorpusReport:
    blockers: list[str] = []
    assets = len(manifest.assets)
    if assets < spec.min_assets:
        blockers.append(f"assets:need>={spec.min_assets},got={assets}")
    if assets > spec.max_assets:
        blockers.append(f"assets:need<={spec.max_assets},got={assets}")

    families = Counter(_format_family(path) for path in manifest.assets)
    if len(families) < spec.min_format_families:
        blockers.append(
            f"format-families:need>={spec.min_format_families},got={len(families)}"
        )

    if token_budget is None:
        # Conservative by default: one character is at least one token for gate
        # qualification. This avoids granting a "large corpus" pass through an
        # English-centric 3-4 chars/token assumption.
        estimated_tokens = manifest.total_chars
    else:
        # CorpusManifest does not retain every raw source string, so exact tokenizer
        # replay belongs to the benchmark runner. Gate 1 remains conservative.
        estimated_tokens = manifest.total_chars

    ratio = (
        estimated_tokens / spec.model_context_tokens
        if spec.model_context_tokens > 0
        else math.inf
    )
    if ratio < spec.min_corpus_to_context_ratio:
        blockers.append(
            "corpus/context-ratio:"
            f"need>={spec.min_corpus_to_context_ratio:g},got={ratio:.3f}"
        )

    reports = manifest.asset_reports
    hash_ready = sum(1 for report in reports if report.source_sha256)
    source_hash_coverage = hash_ready / len(reports) if reports else 0.0
    if spec.require_source_hashes and source_hash_coverage < 1.0:
        blockers.append(
            f"source-hash-coverage:need=1.0,got={source_hash_coverage:.3f}"
        )

    if spec.require_semantic_ready and not manifest.coverage_ready:
        blockers.append("semantic-readiness:false")
    if spec.require_semantic_ready and manifest.semantic_coverage < 1.0:
        blockers.append(
            f"semantic-coverage:need=1.0,got={manifest.semantic_coverage:.3f}"
        )

    return Gate1CorpusReport(
        status=GateStatus.PASS if not blockers else GateStatus.FAIL,
        corpus_id=manifest.corpus_id,
        assets=assets,
        required_blocks=manifest.required_blocks,
        total_bytes=manifest.total_bytes,
        total_chars=manifest.total_chars,
        estimated_tokens=estimated_tokens,
        model_context_tokens=spec.model_context_tokens,
        corpus_to_context_ratio=round(ratio, 4),
        format_families=dict(sorted(families.items())),
        modalities=dict(sorted(manifest.modality_counts.items())),
        source_hash_coverage=source_hash_coverage,
        ingest_coverage=manifest.ingest_coverage,
        semantic_coverage=manifest.semantic_coverage,
        coverage_ready=manifest.coverage_ready,
        blockers=blockers,
    )


class NeedleKind(str, Enum):
    EXACT = "exact"
    SEMANTIC_PARAPHRASE = "semantic-paraphrase"
    NUMBER = "number"
    DATE = "date"
    EXCEPTION = "exception"
    CONTRADICTION = "contradiction"
    SUPERSESSION = "supersession"
    CROSS_FILE = "cross-file"
    TABLE_CELL = "table-cell"
    IMAGE_TEXT = "image-text"
    NEGATIVE = "negative"


class CorpusPosition(str, Enum):
    EARLY = "early"
    MIDDLE = "middle"
    LATE = "late"


class LocalPosition(str, Enum):
    HEAD = "head"
    MIDDLE = "middle"
    TAIL = "tail"


class NeedleCase(BaseModel):
    id: str
    kind: NeedleKind
    question: str
    target_assets: list[str] = Field(default_factory=list)
    expected_present: bool = True
    expected_answer: str | None = None
    match_terms: list[str] = Field(default_factory=list)
    expected_authority: str | None = None
    corpus_position: CorpusPosition
    local_position: LocalPosition
    modality: Modality = Modality.TEXT
    tags: list[str] = Field(default_factory=list)
    required_asset_hits: int | None = None
    match_all_terms: bool = False


class Gate2NeedleSpec(BaseModel):
    min_cases: int = 100
    min_kinds: int = 8
    require_positions: bool = True
    require_negative: bool = True
    require_cross_file: bool = True


class Gate2NeedleMatrixReport(BaseModel):
    gate: int = 2
    status: GateStatus
    total_cases: int
    kind_counts: dict[str, int]
    corpus_position_counts: dict[str, int]
    local_position_counts: dict[str, int]
    modality_counts: dict[str, int]
    blockers: list[str] = Field(default_factory=list)

    def as_gate(self) -> ProofGate:
        return ProofGate(
            gate=2,
            name="Ground-truth Needle Matrix",
            status=self.status,
            blockers=self.blockers,
            metrics=self.model_dump(exclude={"gate", "status", "blockers"}),
        )


def validate_needle_matrix(
    cases: Iterable[NeedleCase],
    spec: Gate2NeedleSpec | None = None,
) -> Gate2NeedleMatrixReport:
    spec = spec or Gate2NeedleSpec()
    items = list(cases)
    kinds = Counter(case.kind.value for case in items)
    corpus_positions = Counter(case.corpus_position.value for case in items)
    local_positions = Counter(case.local_position.value for case in items)
    modalities = Counter(case.modality.value for case in items)
    blockers: list[str] = []

    if len(items) < spec.min_cases:
        blockers.append(f"needle-count:need>={spec.min_cases},got={len(items)}")
    if len(kinds) < spec.min_kinds:
        blockers.append(f"needle-kinds:need>={spec.min_kinds},got={len(kinds)}")
    if spec.require_positions:
        for value in CorpusPosition:
            if not corpus_positions[value.value]:
                blockers.append(f"missing-corpus-position:{value.value}")
        for value in LocalPosition:
            if not local_positions[value.value]:
                blockers.append(f"missing-local-position:{value.value}")
    if spec.require_negative and not kinds[NeedleKind.NEGATIVE.value]:
        blockers.append("missing-kind:negative")
    if spec.require_cross_file and not kinds[NeedleKind.CROSS_FILE.value]:
        blockers.append("missing-kind:cross-file")

    return Gate2NeedleMatrixReport(
        status=GateStatus.PASS if not blockers else GateStatus.FAIL,
        total_cases=len(items),
        kind_counts=dict(sorted(kinds.items())),
        corpus_position_counts=dict(sorted(corpus_positions.items())),
        local_position_counts=dict(sorted(local_positions.items())),
        modality_counts=dict(sorted(modalities.items())),
        blockers=blockers,
    )


def load_needle_matrix(path: str | Path) -> list[NeedleCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("cases", [])
    return [NeedleCase.model_validate(item) for item in raw]


def write_proof_artifact(path: str | Path, payload: BaseModel | dict[str, Any]) -> None:
    obj = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )



class ProofJudge(Protocol):
    route_id: str | None

    def can_inspect(self, block: ContextBlock) -> bool: ...
    def inspect(
        self,
        question: str,
        answer: str,
        block: ContextBlock,
        notes: list[str],
    ) -> tuple[str, bool]: ...
    def score_full(
        self,
        question: str,
        answer: str,
        blocks: list[ContextBlock],
    ) -> tuple[float, str]: ...
    def usage_snapshot(self) -> UsageMetrics: ...


class NeedleRunResult(BaseModel):
    case_id: str
    kind: NeedleKind
    expected_present: bool
    recovered: bool
    term_recall: float
    matched_terms: list[str] = Field(default_factory=list)
    matched_assets: list[str] = Field(default_factory=list)
    relevant_blocks: int = 0
    visited_blocks: int = 0
    total_blocks: int = 0
    unsupported_blocks: int = 0
    coverage: float = 0.0
    judgment_valid: bool = False
    latency_seconds: float = 0.0
    error: str | None = None


class NeedleRecoveryReport(BaseModel):
    corpus_id: str
    route_id: str | None = None
    total_cases: int
    present_cases: int
    negative_cases: int
    evidence_recall: float
    evidence_term_fidelity: float
    negative_accuracy: float
    unsupported_cases: int
    by_kind: dict[str, float]
    by_corpus_position: dict[str, float]
    results: list[NeedleRunResult]


def _normalized(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _term_hits(text: str, terms: list[str]) -> list[str]:
    haystack = _normalized(text)
    return [term for term in terms if _normalized(term) in haystack]


def _asset_matches(path: str, targets: list[str]) -> bool:
    if not targets:
        return True
    name = Path(path).name
    return any(path == target or name == Path(target).name for target in targets)


def _case_recovery_from_result(
    store: FileContextStore,
    corpus_id: str,
    case: NeedleCase,
    result,
) -> tuple[bool, float, list[str], list[str]]:
    matched_terms: set[str] = set()
    matched_assets: set[str] = set()

    for evidence in result.evidence:
        block = store.get_block(corpus_id, evidence.block_id)
        if not _asset_matches(block.source.path, case.target_assets):
            continue
        searchable = "\n".join([block.text or "", evidence.note or ""])
        hits = _term_hits(searchable, case.match_terms)
        if hits:
            matched_terms.update(hits)
            matched_assets.add(Path(block.source.path).name)

    if not case.expected_present:
        # Negative probes should not produce evidence on the absent proposition.
        recovered = len(result.evidence) == 0
        return recovered, 1.0 if recovered else 0.0, [], []

    if not case.match_terms:
        recovered = any(
            _asset_matches(ev.source.path, case.target_assets)
            for ev in result.evidence
        )
        return recovered, 1.0 if recovered else 0.0, [], sorted(matched_assets)

    term_recall = len(matched_terms) / len(set(case.match_terms))
    terms_ok = (
        term_recall >= 1.0
        if case.match_all_terms
        else bool(matched_terms)
    )
    required_asset_hits = case.required_asset_hits
    if required_asset_hits is None:
        required_asset_hits = (
            len(case.target_assets)
            if case.kind == NeedleKind.CROSS_FILE and case.target_assets
            else 1
        )
    assets_ok = len(matched_assets) >= required_asset_hits
    return terms_ok and assets_ok, term_recall, sorted(matched_terms), sorted(matched_assets)


def run_full_coverage_needles(
    store: FileContextStore,
    corpus_id: str,
    judge_factory: Callable[[], ProofJudge],
    cases: Iterable[NeedleCase],
    *,
    max_workers: int = 4,
    reduction_batch_size: int = 32,
) -> NeedleRecoveryReport:
    items = list(cases)
    manifest = store.get_manifest(corpus_id)
    contract = ExecutionContract.full_coverage(manifest.coverage_ids())
    results: list[NeedleRunResult] = []

    for case in items:
        judge = judge_factory()
        evaluator = ProgressiveEvaluator(
            store,
            judge,
            max_workers=max_workers,
            reduction_batch_size=reduction_batch_size,
            retry_attempts=1,
        )
        started = time.perf_counter()
        try:
            execution = evaluator.evaluate(
                corpus_id,
                case.question,
                case.expected_answer or "",
                contract=contract,
            )
            recovered, term_recall, matched_terms, matched_assets = (
                _case_recovery_from_result(
                    store,
                    corpus_id,
                    case,
                    execution,
                )
            )
            results.append(
                NeedleRunResult(
                    case_id=case.id,
                    kind=case.kind,
                    expected_present=case.expected_present,
                    recovered=recovered,
                    term_recall=term_recall,
                    matched_terms=matched_terms,
                    matched_assets=matched_assets,
                    relevant_blocks=len(execution.evidence),
                    visited_blocks=execution.visited_blocks,
                    total_blocks=execution.total_blocks,
                    unsupported_blocks=execution.failed_blocks,
                    coverage=execution.coverage,
                    judgment_valid=execution.judgment_valid,
                    latency_seconds=time.perf_counter() - started,
                )
            )
        except Exception as exc:
            results.append(
                NeedleRunResult(
                    case_id=case.id,
                    kind=case.kind,
                    expected_present=case.expected_present,
                    recovered=False,
                    term_recall=0.0,
                    total_blocks=manifest.required_blocks,
                    latency_seconds=time.perf_counter() - started,
                    error=str(exc),
                )
            )

    present = [r for r in results if r.expected_present]
    negatives = [r for r in results if not r.expected_present]
    evidence_recall = (
        sum(1 for r in present if r.recovered) / len(present)
        if present
        else 1.0
    )
    term_fidelity = (
        sum(r.term_recall for r in present) / len(present)
        if present
        else 1.0
    )
    negative_accuracy = (
        sum(1 for r in negatives if r.recovered) / len(negatives)
        if negatives
        else 1.0
    )

    by_kind: dict[str, float] = {}
    for kind in NeedleKind:
        group = [r for r in results if r.kind == kind]
        if group:
            by_kind[kind.value] = sum(1 for r in group if r.recovered) / len(group)

    by_position: dict[str, float] = {}
    case_by_id = {case.id: case for case in items}
    for position in CorpusPosition:
        group = [
            r for r in results
            if case_by_id[r.case_id].corpus_position == position
        ]
        if group:
            by_position[position.value] = (
                sum(1 for r in group if r.recovered) / len(group)
            )

    return NeedleRecoveryReport(
        corpus_id=corpus_id,
        route_id=(judge_factory().route_id if items else None),
        total_cases=len(results),
        present_cases=len(present),
        negative_cases=len(negatives),
        evidence_recall=evidence_recall,
        evidence_term_fidelity=term_fidelity,
        negative_accuracy=negative_accuracy,
        unsupported_cases=sum(1 for r in results if r.unsupported_blocks or r.error),
        by_kind=dict(sorted(by_kind.items())),
        by_corpus_position=dict(sorted(by_position.items())),
        results=results,
    )


class TaskCase(BaseModel):
    id: str
    question: str
    candidate_answer: str
    expected_min_score: float | None = None
    expected_max_score: float | None = None
    tags: list[str] = Field(default_factory=list)


class BaselineTaskResult(BaseModel):
    baseline: str
    task_id: str
    score: float | None = None
    correct: bool = False
    blocked: bool = False
    latency_seconds: float = 0.0
    selected_blocks: int = 0
    coverage: float | None = None
    estimated_cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


class BaselineSummary(BaseModel):
    baseline: str
    total_tasks: int
    completed_tasks: int
    blocked_tasks: int
    task_accuracy: float
    latency_seconds: float
    estimated_cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    results: list[BaselineTaskResult]


def _score_is_correct(case: TaskCase, score: float | None) -> bool:
    if score is None:
        return False
    if case.expected_min_score is not None and score < case.expected_min_score:
        return False
    if case.expected_max_score is not None and score > case.expected_max_score:
        return False
    return True


def _summarize_baseline(
    baseline: str,
    results: list[BaselineTaskResult],
) -> BaselineSummary:
    completed = [x for x in results if not x.blocked and x.score is not None]
    return BaselineSummary(
        baseline=baseline,
        total_tasks=len(results),
        completed_tasks=len(completed),
        blocked_tasks=sum(1 for x in results if x.blocked),
        task_accuracy=(
            sum(1 for x in completed if x.correct) / len(completed)
            if completed
            else 0.0
        ),
        latency_seconds=sum(x.latency_seconds for x in results),
        estimated_cost_usd=sum(x.estimated_cost_usd for x in results),
        prompt_tokens=sum(x.prompt_tokens for x in results),
        completion_tokens=sum(x.completion_tokens for x in results),
        results=results,
    )


def _usage_for(judge: ProofJudge) -> UsageMetrics:
    try:
        return judge.usage_snapshot()
    except Exception:
        return UsageMetrics(route_id=getattr(judge, "route_id", None))


def run_task_baselines(
    store: FileContextStore,
    corpus_id: str,
    judge_factory: Callable[[], ProofJudge],
    cases: Iterable[TaskCase],
    *,
    lexical_top_ks: tuple[int, ...] = (5, 20),
    include_full_coverage: bool = True,
    include_direct: bool = True,
    max_workers: int = 4,
) -> list[BaselineSummary]:
    items = list(cases)
    reader = CorpusReader(store, corpus_id)
    manifest = store.get_manifest(corpus_id)
    summaries: list[BaselineSummary] = []

    for top_k in lexical_top_ks:
        rows: list[BaselineTaskResult] = []
        for case in items:
            judge = judge_factory()
            selected_ids = reader.lexical_order(case.question)[:top_k]
            blocks = [reader.read(block_id) for block_id in selected_ids]
            started = time.perf_counter()
            try:
                score, _ = judge.score_full(
                    case.question,
                    case.candidate_answer,
                    blocks,
                )
                usage = _usage_for(judge)
                rows.append(
                    BaselineTaskResult(
                        baseline=f"lexical-top-{top_k}",
                        task_id=case.id,
                        score=score,
                        correct=_score_is_correct(case, score),
                        latency_seconds=time.perf_counter() - started,
                        selected_blocks=len(blocks),
                        coverage=(
                            len(blocks) / manifest.required_blocks
                            if manifest.required_blocks
                            else 1.0
                        ),
                        estimated_cost_usd=usage.estimated_cost_usd,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                    )
                )
            except Exception as exc:
                rows.append(
                    BaselineTaskResult(
                        baseline=f"lexical-top-{top_k}",
                        task_id=case.id,
                        blocked=True,
                        latency_seconds=time.perf_counter() - started,
                        selected_blocks=len(blocks),
                        error=str(exc),
                    )
                )
        summaries.append(_summarize_baseline(f"lexical-top-{top_k}", rows))

    if include_full_coverage:
        rows = []
        contract = ExecutionContract.full_coverage(manifest.coverage_ids())
        for case in items:
            judge = judge_factory()
            started = time.perf_counter()
            try:
                result = ProgressiveEvaluator(
                    store,
                    judge,
                    max_workers=max_workers,
                    retry_attempts=1,
                ).evaluate(
                    corpus_id,
                    case.question,
                    case.candidate_answer,
                    contract=contract,
                )
                rows.append(
                    BaselineTaskResult(
                        baseline="contextmesh-full-coverage",
                        task_id=case.id,
                        score=result.score,
                        correct=(
                            result.judgment_valid
                            and _score_is_correct(case, result.score)
                        ),
                        blocked=not result.judgment_valid,
                        latency_seconds=time.perf_counter() - started,
                        selected_blocks=result.visited_blocks,
                        coverage=result.coverage,
                        estimated_cost_usd=result.usage.estimated_cost_usd,
                        prompt_tokens=result.usage.prompt_tokens,
                        completion_tokens=result.usage.completion_tokens,
                        error=(
                            "; ".join(result.finalization_blockers)
                            if result.finalization_blockers
                            else None
                        ),
                    )
                )
            except Exception as exc:
                rows.append(
                    BaselineTaskResult(
                        baseline="contextmesh-full-coverage",
                        task_id=case.id,
                        blocked=True,
                        latency_seconds=time.perf_counter() - started,
                        error=str(exc),
                    )
                )
        summaries.append(
            _summarize_baseline("contextmesh-full-coverage", rows)
        )

    if include_direct:
        rows = []
        blocks = [reader.read(block_id) for block_id in reader.required_ids]
        for case in items:
            judge = judge_factory()
            started = time.perf_counter()
            try:
                score, _ = judge.score_full(
                    case.question,
                    case.candidate_answer,
                    blocks,
                )
                usage = _usage_for(judge)
                rows.append(
                    BaselineTaskResult(
                        baseline="direct-full-context",
                        task_id=case.id,
                        score=score,
                        correct=_score_is_correct(case, score),
                        latency_seconds=time.perf_counter() - started,
                        selected_blocks=len(blocks),
                        coverage=1.0,
                        estimated_cost_usd=usage.estimated_cost_usd,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                    )
                )
            except Exception as exc:
                rows.append(
                    BaselineTaskResult(
                        baseline="direct-full-context",
                        task_id=case.id,
                        blocked=True,
                        latency_seconds=time.perf_counter() - started,
                        selected_blocks=len(blocks),
                        coverage=1.0,
                        error=str(exc),
                    )
                )
        summaries.append(_summarize_baseline("direct-full-context", rows))

    return summaries


class Gate3Spec(BaseModel):
    min_evidence_recall: float = 0.90
    min_evidence_term_fidelity: float = 0.90
    min_negative_accuracy: float = 0.95
    min_task_accuracy: float = 0.90
    require_zero_unsupported_cases: bool = True


class Gate3Report(BaseModel):
    gate: int = 3
    status: GateStatus
    corpus_id: str
    needle: NeedleRecoveryReport
    baselines: list[BaselineSummary]
    blockers: list[str] = Field(default_factory=list)

    def as_gate(self) -> ProofGate:
        contextmesh = next(
            (
                baseline
                for baseline in self.baselines
                if baseline.baseline == "contextmesh-full-coverage"
            ),
            None,
        )
        return ProofGate(
            gate=3,
            name="Evidence + Task + Baseline",
            status=self.status,
            blockers=self.blockers,
            metrics={
                "evidence_recall": self.needle.evidence_recall,
                "evidence_term_fidelity": self.needle.evidence_term_fidelity,
                "negative_accuracy": self.needle.negative_accuracy,
                "task_accuracy": (
                    contextmesh.task_accuracy if contextmesh else None
                ),
                "baselines": {
                    baseline.baseline: {
                        "task_accuracy": baseline.task_accuracy,
                        "blocked_tasks": baseline.blocked_tasks,
                        "latency_seconds": baseline.latency_seconds,
                        "estimated_cost_usd": baseline.estimated_cost_usd,
                    }
                    for baseline in self.baselines
                },
            },
        )


def evaluate_gate3(
    needle: NeedleRecoveryReport,
    baselines: list[BaselineSummary],
    spec: Gate3Spec | None = None,
) -> Gate3Report:
    spec = spec or Gate3Spec()
    blockers: list[str] = []
    if needle.evidence_recall < spec.min_evidence_recall:
        blockers.append(
            f"evidence-recall:need>={spec.min_evidence_recall:.3f},"
            f"got={needle.evidence_recall:.3f}"
        )
    if needle.evidence_term_fidelity < spec.min_evidence_term_fidelity:
        blockers.append(
            f"evidence-term-fidelity:need>={spec.min_evidence_term_fidelity:.3f},"
            f"got={needle.evidence_term_fidelity:.3f}"
        )
    if needle.negative_accuracy < spec.min_negative_accuracy:
        blockers.append(
            f"negative-accuracy:need>={spec.min_negative_accuracy:.3f},"
            f"got={needle.negative_accuracy:.3f}"
        )
    if spec.require_zero_unsupported_cases and needle.unsupported_cases:
        blockers.append(f"unsupported-cases={needle.unsupported_cases}")

    contextmesh = next(
        (
            baseline
            for baseline in baselines
            if baseline.baseline == "contextmesh-full-coverage"
        ),
        None,
    )
    if contextmesh is None:
        blockers.append("missing-baseline:contextmesh-full-coverage")
    elif contextmesh.task_accuracy < spec.min_task_accuracy:
        blockers.append(
            f"task-accuracy:need>={spec.min_task_accuracy:.3f},"
            f"got={contextmesh.task_accuracy:.3f}"
        )

    return Gate3Report(
        status=GateStatus.PASS if not blockers else GateStatus.FAIL,
        corpus_id=needle.corpus_id,
        needle=needle,
        baselines=baselines,
        blockers=blockers,
    )
