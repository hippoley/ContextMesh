from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from .models import CorpusManifest, Modality
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
