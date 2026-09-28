from __future__ import annotations

import hashlib
import json
import math
import time
import tempfile
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from pydantic import BaseModel, Field

from .models import ContextBlock, CorpusManifest, ModelRoute, Modality, UsageMetrics
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
    min_modalities: int = 2
    require_positions: bool = True
    require_negative: bool = True
    require_cross_file: bool = True
    require_target_assets: bool = True
    require_match_terms: bool = True


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
    *,
    manifest: CorpusManifest | None = None,
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
    if len(modalities) < spec.min_modalities:
        blockers.append(
            f"needle-modalities:need>={spec.min_modalities},got={len(modalities)}"
        )
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

    if spec.require_target_assets:
        missing_targets = [
            case.id
            for case in items
            if case.expected_present and not case.target_assets
        ]
        if missing_targets:
            blockers.append(f"missing-target-assets={len(missing_targets)}")

    if spec.require_match_terms:
        missing_terms = [case.id for case in items if not case.match_terms]
        if missing_terms:
            blockers.append(f"missing-match-terms={len(missing_terms)}")

    if manifest is not None:
        known_assets = {Path(path).name for path in manifest.assets}
        unknown: set[str] = set()
        for case in items:
            for target in case.target_assets:
                if Path(target).name not in known_assets:
                    unknown.add(Path(target).name)
        if unknown:
            blockers.append(
                "unknown-target-assets:" + ",".join(sorted(unknown)[:20])
            )

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
    tags: list[str] = Field(default_factory=list)


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
    accuracy_by_tag: dict[str, float] = Field(default_factory=dict)
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
    tags = sorted({tag for row in completed for tag in row.tags})
    accuracy_by_tag: dict[str, float] = {}
    for tag in tags:
        group = [row for row in completed if tag in row.tags]
        if group:
            accuracy_by_tag[tag] = (
                sum(1 for row in group if row.correct) / len(group)
            )
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
        accuracy_by_tag=dict(sorted(accuracy_by_tag.items())),
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
                        tags=list(case.tags),
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
                        tags=list(case.tags),
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
                        tags=list(case.tags),
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
                        tags=list(case.tags),
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
                        tags=list(case.tags),
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
                        tags=list(case.tags),
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



class ScalePointStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"


class ScalePointResult(BaseModel):
    requested_ratio: float
    actual_ratio: float = 0.0
    status: ScalePointStatus
    selected_blocks: int = 0
    selected_assets: int = 0
    estimated_tokens: int = 0
    evidence_recall: float | None = None
    evidence_term_fidelity: float | None = None
    negative_accuracy: float | None = None
    task_accuracy: float | None = None
    baseline_task_accuracy: dict[str, float] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)


class Gate4Spec(BaseModel):
    ratios: list[float] = Field(default_factory=lambda: [1, 2, 5, 10, 20])
    model_context_tokens: int
    needle_sample_size: int = 24
    task_sample_size: int = 12
    min_evidence_recall: float = 0.90
    min_task_accuracy: float = 0.90
    max_recall_drop: float = 0.05
    required_max_ratio: float = 20.0


class Gate4Report(BaseModel):
    gate: int = 4
    status: GateStatus
    corpus_id: str
    model_context_tokens: int
    points: list[ScalePointResult]
    max_completed_ratio: float = 0.0
    recall_drop: float = 0.0
    blockers: list[str] = Field(default_factory=list)

    def as_gate(self) -> ProofGate:
        return ProofGate(
            gate=4,
            name="Scale Curve",
            status=self.status,
            blockers=self.blockers,
            metrics={
                "model_context_tokens": self.model_context_tokens,
                "max_completed_ratio": self.max_completed_ratio,
                "recall_drop": self.recall_drop,
                "points": [point.model_dump(mode="json") for point in self.points],
            },
        )


def _stratified_needles(
    cases: list[NeedleCase],
    limit: int,
) -> list[NeedleCase]:
    if limit <= 0 or len(cases) <= limit:
        return list(cases)
    groups: dict[NeedleKind, list[NeedleCase]] = {}
    for case in sorted(cases, key=lambda x: x.id):
        groups.setdefault(case.kind, []).append(case)
    out: list[NeedleCase] = []
    while len(out) < limit:
        progressed = False
        for kind in sorted(groups, key=lambda x: x.value):
            group = groups[kind]
            if group:
                out.append(group.pop(0))
                progressed = True
                if len(out) >= limit:
                    break
        if not progressed:
            break
    return out


def _anchor_blocks(
    store: FileContextStore,
    corpus_id: str,
    cases: list[NeedleCase],
) -> set[str]:
    manifest = store.get_manifest(corpus_id)
    targets = {
        Path(asset).name
        for case in cases
        for asset in case.target_assets
    }
    if not targets:
        return set()
    out: set[str] = set()
    for block_id in manifest.coverage_ids():
        block = store.get_block(corpus_id, block_id)
        if Path(block.source.path).name in targets:
            out.add(block_id)
    return out


def _block_token_estimate(block: ContextBlock) -> int:
    # Same conservative qualification rule as Gate 1. Provider-exact tokenization
    # remains a route-level runtime concern.
    return max(1, len(block.text or ""))


def _plan_scale_projection(
    store: FileContextStore,
    corpus_id: str,
    cases: list[NeedleCase],
    *,
    target_tokens: int,
) -> tuple[list[str], int, list[str]]:
    manifest = store.get_manifest(corpus_id)
    ordered = manifest.coverage_ids()
    anchors = _anchor_blocks(store, corpus_id, cases)
    selected: list[str] = []
    selected_set: set[str] = set()
    total = 0

    for block_id in ordered:
        if block_id not in anchors:
            continue
        block = store.get_block(corpus_id, block_id)
        selected.append(block_id)
        selected_set.add(block_id)
        total += _block_token_estimate(block)

    blockers: list[str] = []
    if total > target_tokens:
        blockers.append(
            f"anchor-evidence-exceeds-target:anchors={total},target={target_tokens}"
        )
        return selected, total, blockers

    for block_id in ordered:
        if block_id in selected_set:
            continue
        block = store.get_block(corpus_id, block_id)
        cost = _block_token_estimate(block)
        selected.append(block_id)
        selected_set.add(block_id)
        total += cost
        # Coverage units stay whole. The last block may overshoot the requested
        # ratio; actual_ratio records what was really executed.
        if total >= target_tokens:
            break

    if total < target_tokens:
        blockers.append(
            f"source-corpus-too-small:available={total},target={target_tokens}"
        )
    return selected, total, blockers


def _materialize_projection(
    source: FileContextStore,
    source_corpus_id: str,
    destination: FileContextStore,
    target_corpus_id: str,
    block_ids: list[str],
) -> CorpusManifest:
    source_manifest = source.get_manifest(source_corpus_id)
    selected = set(block_ids)
    source_blocks = [source.get_block(source_corpus_id, block_id) for block_id in block_ids]
    blocks: list[ContextBlock] = []
    for block in source_blocks:
        blocks.append(
            block.model_copy(
                update={
                    "corpus_id": target_corpus_id,
                    "parent_id": block.parent_id if block.parent_id in selected else None,
                    "children_ids": [x for x in block.children_ids if x in selected],
                    "prev_id": block.prev_id if block.prev_id in selected else None,
                    "next_id": block.next_id if block.next_id in selected else None,
                }
            )
        )
    destination.put_blocks(blocks)

    assets = sorted({block.source.path for block in blocks})
    reports = [
        report
        for report in source_manifest.asset_reports
        if report.path in assets or Path(report.path).name in {Path(x).name for x in assets}
    ]
    modality_counts = Counter(block.modality.value for block in blocks)
    required_capabilities = sorted(
        {cap for block in blocks for cap in block.required_capabilities}
    )
    unresolved = sum(
        1 for block in blocks if not block.processable or block.semantic_status.value != "ready"
    )
    total_bytes = sum(report.bytes for report in reports)

    manifest = CorpusManifest(
        schema_version=source_manifest.schema_version,
        corpus_id=target_corpus_id,
        assets=assets,
        root_block_ids=[],
        structural_block_ids=[],
        block_ids=list(block_ids),
        required_block_ids=list(block_ids),
        total_blocks=len(blocks),
        required_blocks=len(blocks),
        total_chars=sum(len(block.text or "") for block in blocks),
        total_bytes=total_bytes,
        modality_counts=dict(sorted(modality_counts.items())),
        required_capabilities=required_capabilities,
        ingest_warnings=[],
        asset_reports=reports,
        ingest_coverage=1.0,
        semantic_coverage=(len(blocks) - unresolved) / len(blocks) if blocks else 1.0,
        unresolved_units=unresolved,
        coverage_ready=unresolved == 0,
    )
    destination.put_manifest(manifest)
    return manifest


def run_scale_curve(
    store: FileContextStore,
    corpus_id: str,
    judge_factory: Callable[[], ProofJudge],
    needle_cases: Iterable[NeedleCase],
    task_cases: Iterable[TaskCase],
    spec: Gate4Spec,
) -> Gate4Report:
    needles_all = list(needle_cases)
    tasks_all = list(task_cases)
    needles = _stratified_needles(needles_all, spec.needle_sample_size)
    tasks = sorted(tasks_all, key=lambda x: x.id)[: spec.task_sample_size]
    points: list[ScalePointResult] = []

    for ratio in spec.ratios:
        target_tokens = int(spec.model_context_tokens * ratio)
        block_ids, estimated_tokens, plan_blockers = _plan_scale_projection(
            store,
            corpus_id,
            needles,
            target_tokens=target_tokens,
        )
        if plan_blockers:
            points.append(
                ScalePointResult(
                    requested_ratio=ratio,
                    actual_ratio=(
                        estimated_tokens / spec.model_context_tokens
                        if spec.model_context_tokens
                        else 0.0
                    ),
                    status=ScalePointStatus.BLOCKED,
                    selected_blocks=len(block_ids),
                    estimated_tokens=estimated_tokens,
                    blockers=plan_blockers,
                )
            )
            continue

        with tempfile.TemporaryDirectory(prefix="contextmesh-scale-") as tmp:
            projected_store = FileContextStore(Path(tmp) / "store")
            projected_id = f"{corpus_id}__scale_{str(ratio).replace('.', '_')}"
            projected = _materialize_projection(
                store,
                corpus_id,
                projected_store,
                projected_id,
                block_ids,
            )
            needle_report = run_full_coverage_needles(
                projected_store,
                projected_id,
                judge_factory,
                needles,
            )
            baselines = run_task_baselines(
                projected_store,
                projected_id,
                judge_factory,
                tasks,
                lexical_top_ks=(5, 20),
                include_direct=True,
            )
            by_name = {item.baseline: item for item in baselines}
            cm = by_name.get("contextmesh-full-coverage")
            point_blockers: list[str] = []
            if needle_report.evidence_recall < spec.min_evidence_recall:
                point_blockers.append(
                    f"evidence-recall={needle_report.evidence_recall:.3f}"
                )
            if cm is None or cm.task_accuracy < spec.min_task_accuracy:
                point_blockers.append(
                    f"task-accuracy={(cm.task_accuracy if cm else 0.0):.3f}"
                )
            points.append(
                ScalePointResult(
                    requested_ratio=ratio,
                    actual_ratio=(
                        estimated_tokens / spec.model_context_tokens
                        if spec.model_context_tokens
                        else 0.0
                    ),
                    status=(
                        ScalePointStatus.PASS
                        if not point_blockers
                        else ScalePointStatus.FAIL
                    ),
                    selected_blocks=projected.required_blocks,
                    selected_assets=len(projected.assets),
                    estimated_tokens=estimated_tokens,
                    evidence_recall=needle_report.evidence_recall,
                    evidence_term_fidelity=needle_report.evidence_term_fidelity,
                    negative_accuracy=needle_report.negative_accuracy,
                    task_accuracy=cm.task_accuracy if cm else None,
                    baseline_task_accuracy={
                        name: row.task_accuracy for name, row in sorted(by_name.items())
                    },
                    blockers=point_blockers,
                )
            )

    completed = [
        point for point in points
        if point.status != ScalePointStatus.BLOCKED
        and point.evidence_recall is not None
    ]
    blockers: list[str] = []
    max_completed_ratio = max(
        (point.actual_ratio for point in completed),
        default=0.0,
    )
    if max_completed_ratio < spec.required_max_ratio:
        blockers.append(
            f"max-ratio:need>={spec.required_max_ratio:g},got={max_completed_ratio:.3f}"
        )

    recall_drop = 0.0
    if completed:
        first_recall = completed[0].evidence_recall or 0.0
        lowest_recall = min(point.evidence_recall or 0.0 for point in completed)
        recall_drop = max(0.0, first_recall - lowest_recall)
        if recall_drop > spec.max_recall_drop:
            blockers.append(
                f"recall-drop:need<={spec.max_recall_drop:.3f},got={recall_drop:.3f}"
            )
    for point in points:
        if point.status == ScalePointStatus.FAIL:
            blockers.append(f"scale-point-failed:{point.requested_ratio:g}x")
        if point.status == ScalePointStatus.BLOCKED:
            blockers.append(f"scale-point-blocked:{point.requested_ratio:g}x")

    return Gate4Report(
        status=GateStatus.PASS if not blockers else GateStatus.FAIL,
        corpus_id=corpus_id,
        model_context_tokens=spec.model_context_tokens,
        points=points,
        max_completed_ratio=max_completed_ratio,
        recall_drop=recall_drop,
        blockers=blockers,
    )


class ProofRunSnapshot(BaseModel):
    run_id: str
    route_id: str
    model: str
    model_version: str | None = None
    prompt_version: str | None = None
    chunk_policy: str | None = None
    reducer_policy: str | None = None
    evidence_recall: float
    task_accuracy: float
    authority_accuracy: float | None = None
    negative_accuracy: float
    estimated_cost_usd: float = 0.0
    latency_seconds: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def config_fingerprint(self) -> str:
        payload = {
            "route_id": self.route_id,
            "model": self.model,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "chunk_policy": self.chunk_policy,
            "reducer_policy": self.reducer_policy,
            "metadata": self.metadata,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class DriftDelta(BaseModel):
    run_id: str
    reference_run_id: str
    evidence_recall_delta: float
    task_accuracy_delta: float
    authority_accuracy_delta: float | None = None
    negative_accuracy_delta: float
    cost_ratio: float | None = None
    latency_ratio: float | None = None
    config_fingerprint: str
    blockers: list[str] = Field(default_factory=list)


class Gate5Spec(BaseModel):
    max_evidence_recall_drop: float = 0.05
    max_task_accuracy_drop: float = 0.05
    max_authority_accuracy_drop: float = 0.02
    max_negative_accuracy_drop: float = 0.02
    max_cost_ratio: float | None = None
    max_latency_ratio: float | None = None


class Gate5Report(BaseModel):
    gate: int = 5
    status: GateStatus
    reference: ProofRunSnapshot
    deltas: list[DriftDelta]
    blockers: list[str] = Field(default_factory=list)

    def as_gate(self) -> ProofGate:
        return ProofGate(
            gate=5,
            name="Drift",
            status=self.status,
            blockers=self.blockers,
            metrics={
                "reference_run_id": self.reference.run_id,
                "reference_fingerprint": self.reference.config_fingerprint,
                "deltas": [delta.model_dump(mode="json") for delta in self.deltas],
            },
        )


def _ratio(candidate: float, reference: float) -> float | None:
    if reference <= 0:
        return None
    return candidate / reference


def evaluate_gate5_drift(
    reference: ProofRunSnapshot,
    candidates: Iterable[ProofRunSnapshot],
    spec: Gate5Spec | None = None,
) -> Gate5Report:
    spec = spec or Gate5Spec()
    deltas: list[DriftDelta] = []
    all_blockers: list[str] = []

    for candidate in candidates:
        blockers: list[str] = []
        evidence_delta = candidate.evidence_recall - reference.evidence_recall
        task_delta = candidate.task_accuracy - reference.task_accuracy
        negative_delta = candidate.negative_accuracy - reference.negative_accuracy
        authority_delta = None
        if (
            reference.authority_accuracy is not None
            and candidate.authority_accuracy is not None
        ):
            authority_delta = (
                candidate.authority_accuracy - reference.authority_accuracy
            )

        if evidence_delta < -spec.max_evidence_recall_drop:
            blockers.append(
                f"evidence-recall-drop={-evidence_delta:.3f}"
            )
        if task_delta < -spec.max_task_accuracy_drop:
            blockers.append(
                f"task-accuracy-drop={-task_delta:.3f}"
            )
        if negative_delta < -spec.max_negative_accuracy_drop:
            blockers.append(
                f"negative-accuracy-drop={-negative_delta:.3f}"
            )
        if (
            authority_delta is not None
            and authority_delta < -spec.max_authority_accuracy_drop
        ):
            blockers.append(
                f"authority-accuracy-drop={-authority_delta:.3f}"
            )

        cost_ratio = _ratio(
            candidate.estimated_cost_usd,
            reference.estimated_cost_usd,
        )
        latency_ratio = _ratio(
            candidate.latency_seconds,
            reference.latency_seconds,
        )
        if (
            spec.max_cost_ratio is not None
            and cost_ratio is not None
            and cost_ratio > spec.max_cost_ratio
        ):
            blockers.append(f"cost-ratio={cost_ratio:.3f}")
        if (
            spec.max_latency_ratio is not None
            and latency_ratio is not None
            and latency_ratio > spec.max_latency_ratio
        ):
            blockers.append(f"latency-ratio={latency_ratio:.3f}")

        delta = DriftDelta(
            run_id=candidate.run_id,
            reference_run_id=reference.run_id,
            evidence_recall_delta=evidence_delta,
            task_accuracy_delta=task_delta,
            authority_accuracy_delta=authority_delta,
            negative_accuracy_delta=negative_delta,
            cost_ratio=cost_ratio,
            latency_ratio=latency_ratio,
            config_fingerprint=candidate.config_fingerprint,
            blockers=blockers,
        )
        deltas.append(delta)
        all_blockers.extend(
            f"{candidate.run_id}:{blocker}" for blocker in blockers
        )

    return Gate5Report(
        status=GateStatus.PASS if not all_blockers else GateStatus.FAIL,
        reference=reference,
        deltas=deltas,
        blockers=all_blockers,
    )



def load_task_cases(path: str | Path) -> list[TaskCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("cases", [])
    return [TaskCase.model_validate(item) for item in raw]


def snapshot_from_gate3(
    gate3: Gate3Report,
    route: ModelRoute,
    *,
    run_id: str,
    model_version: str | None = None,
    prompt_version: str | None = None,
    chunk_policy: str | None = None,
    reducer_policy: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProofRunSnapshot:
    contextmesh = next(
        baseline
        for baseline in gate3.baselines
        if baseline.baseline == "contextmesh-full-coverage"
    )
    return ProofRunSnapshot(
        run_id=run_id,
        route_id=route.id,
        model=route.model,
        model_version=model_version,
        prompt_version=prompt_version,
        chunk_policy=chunk_policy,
        reducer_policy=reducer_policy,
        evidence_recall=gate3.needle.evidence_recall,
        task_accuracy=contextmesh.task_accuracy,
        authority_accuracy=contextmesh.accuracy_by_tag.get("authority"),
        negative_accuracy=gate3.needle.negative_accuracy,
        estimated_cost_usd=contextmesh.estimated_cost_usd,
        latency_seconds=contextmesh.latency_seconds,
        metadata=metadata or {},
    )


class BigContextProofReport(BaseModel):
    schema_version: int = 1
    corpus_id: str
    route_id: str
    run_id: str
    gate1: Gate1CorpusReport
    gate2: Gate2NeedleMatrixReport
    gate3: Gate3Report | None = None
    gate4: Gate4Report | None = None
    gate5: Gate5Report | None = None
    snapshot: ProofRunSnapshot | None = None
    claim_proven: bool = False
    blockers: list[str] = Field(default_factory=list)

    def gate_summary(self) -> list[ProofGate]:
        out = [self.gate1.as_gate(), self.gate2.as_gate()]
        if self.gate3 is None:
            out.append(
                ProofGate(
                    gate=3,
                    name="Evidence + Task + Baseline",
                    status=GateStatus.NOT_RUN,
                    blockers=["prerequisite gate failed or live run not executed"],
                )
            )
        else:
            out.append(self.gate3.as_gate())
        if self.gate4 is None:
            out.append(
                ProofGate(
                    gate=4,
                    name="Scale Curve",
                    status=GateStatus.NOT_RUN,
                    blockers=["Gate 3 must pass before scale execution"],
                )
            )
        else:
            out.append(self.gate4.as_gate())
        if self.gate5 is None:
            out.append(
                ProofGate(
                    gate=5,
                    name="Drift",
                    status=GateStatus.NOT_RUN,
                    blockers=["requires a repeated run against a stored reference snapshot"],
                )
            )
        else:
            out.append(self.gate5.as_gate())
        return out


def assemble_big_context_proof(
    *,
    corpus_id: str,
    route_id: str,
    run_id: str,
    gate1: Gate1CorpusReport,
    gate2: Gate2NeedleMatrixReport,
    gate3: Gate3Report | None,
    gate4: Gate4Report | None,
    gate5: Gate5Report | None,
    snapshot: ProofRunSnapshot | None,
) -> BigContextProofReport:
    gates = [
        gate1.status == GateStatus.PASS,
        gate2.status == GateStatus.PASS,
        gate3 is not None and gate3.status == GateStatus.PASS,
        gate4 is not None and gate4.status == GateStatus.PASS,
        gate5 is not None and gate5.status == GateStatus.PASS,
    ]
    blockers: list[str] = []
    if gate1.status != GateStatus.PASS:
        blockers.extend(f"gate1:{x}" for x in gate1.blockers)
    if gate2.status != GateStatus.PASS:
        blockers.extend(f"gate2:{x}" for x in gate2.blockers)
    if gate3 is None:
        blockers.append("gate3:not-run")
    elif gate3.status != GateStatus.PASS:
        blockers.extend(f"gate3:{x}" for x in gate3.blockers)
    if gate4 is None:
        blockers.append("gate4:not-run")
    elif gate4.status != GateStatus.PASS:
        blockers.extend(f"gate4:{x}" for x in gate4.blockers)
    if gate5 is None:
        blockers.append("gate5:not-run")
    elif gate5.status != GateStatus.PASS:
        blockers.extend(f"gate5:{x}" for x in gate5.blockers)

    return BigContextProofReport(
        corpus_id=corpus_id,
        route_id=route_id,
        run_id=run_id,
        gate1=gate1,
        gate2=gate2,
        gate3=gate3,
        gate4=gate4,
        gate5=gate5,
        snapshot=snapshot,
        claim_proven=all(gates),
        blockers=blockers,
    )
