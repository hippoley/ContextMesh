from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, computed_field


class Modality(str, Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    UNKNOWN = "unknown"


class BlockKind(str, Enum):
    ASSET = "asset"
    SECTION = "section"
    CONTENT = "content"
    TABLE = "table"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class SemanticStatus(str, Enum):
    """Whether the block has an addressable representation suitable for semantic inspection."""
    READY = "ready"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"


class SourceRef(BaseModel):
    asset_id: str
    path: str
    locator: dict[str, Any] = Field(default_factory=dict)


class ContextBlock(BaseModel):
    id: str
    corpus_id: str
    modality: Modality = Modality.TEXT
    kind: BlockKind = BlockKind.CONTENT
    text: str = ""
    title: str | None = None
    source: SourceRef
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    prev_id: str | None = None
    next_id: str | None = None
    depth: int = 0
    processable: bool = True
    semantic_status: SemanticStatus = SemanticStatus.READY
    required_capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetCoverageReport(BaseModel):
    path: str
    parser: str
    bytes: int = 0
    source_sha256: str | None = None
    status: str = "complete"  # complete | partial | failed
    resolved_units: int = 0
    unresolved_units: int = 0
    modalities: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def semantic_coverage(self) -> float:
        total = self.resolved_units + self.unresolved_units
        return self.resolved_units / total if total else 1.0


class CorpusManifest(BaseModel):
    schema_version: str = "0.8"
    corpus_id: str
    assets: list[str]
    root_block_ids: list[str] = Field(default_factory=list)
    structural_block_ids: list[str] = Field(default_factory=list)
    block_ids: list[str]
    required_block_ids: list[str] = Field(default_factory=list)
    total_blocks: int
    required_blocks: int = 0
    total_chars: int
    total_bytes: int = 0
    modality_counts: dict[str, int] = Field(default_factory=dict)
    required_capabilities: list[str] = Field(default_factory=list)
    ingest_warnings: list[str] = Field(default_factory=list)
    asset_reports: list[AssetCoverageReport] = Field(default_factory=list)
    ingest_coverage: float = 1.0
    semantic_coverage: float = 1.0
    unresolved_units: int = 0
    coverage_ready: bool = True

    def coverage_ids(self) -> list[str]:
        return self.required_block_ids or self.block_ids


class EvidenceKind(str, Enum):
    CLAIM = "claim"
    NUMBER = "number"
    DATE = "date"
    EXCEPTION = "exception"
    CONTRADICTION = "contradiction"
    REQUIREMENT = "requirement"
    ENTITY = "entity"
    OTHER = "other"


class EvidenceAtom(BaseModel):
    kind: EvidenceKind = EvidenceKind.CLAIM
    text: str
    normalized_value: str | None = None
    unit: str | None = None
    date: str | None = None
    polarity: str = "affirm"
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    block_id: str
    note: str
    source: SourceRef
    modality: Modality | None = None
    atoms: list[EvidenceAtom] = Field(default_factory=list)


class ReductionNode(BaseModel):
    id: str
    level: int
    input_count: int
    summary: str


class UsageMetrics(BaseModel):
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    latency_seconds: float = 0.0
    estimated_cost_usd: float = 0.0
    route_id: str | None = None


class EvaluationState(BaseModel):
    corpus_id: str
    question: str
    answer: str
    visited: set[str] = Field(default_factory=set)
    evidence: list[Evidence] = Field(default_factory=list)
    working_notes: list[str] = Field(default_factory=list)
    reduced_notes: list[str] = Field(default_factory=list)
    reduction_nodes: list[ReductionNode] = Field(default_factory=list)
    failures: dict[str, str] = Field(default_factory=dict)
    inspection_attempts: dict[str, int] = Field(default_factory=dict)
    usage: UsageMetrics = Field(default_factory=UsageMetrics)

    def model_context_notes(self) -> list[str]:
        return [*self.reduced_notes, *self.working_notes]


class EvaluationCheckpoint(BaseModel):
    job_id: str
    corpus_id: str
    ordered_block_ids: list[str]
    cursor: int = 0
    state: EvaluationState
    complete: bool = False
    final_score: float | None = None
    final_rationale: str | None = None
    status: str = "queued"


class EvaluationResult(BaseModel):
    corpus_id: str
    score: float | None
    coverage: float
    complete: bool
    visited_blocks: int
    total_blocks: int
    evidence: list[Evidence]
    rationale: str
    job_id: str | None = None
    reduction_nodes: int = 0
    reduced_context_items: int = 0
    failed_blocks: int = 0
    inspection_attempts: int = 0
    execution_mode: str = "sequential"
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    ingest_coverage: float = 1.0
    semantic_coverage: float = 1.0
    ingest_ready: bool = True
    evidence_atoms: int = 0
    evidence_kind_counts: dict[str, int] = Field(default_factory=dict)


class IngestStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class AssetIngestState(BaseModel):
    filename: str
    path: str
    status: IngestStatus = IngestStatus.QUEUED
    bytes: int = 0
    required_blocks: int = 0
    semantic_coverage: float = 0.0
    unresolved_units: int = 0
    message: str = ""


class IngestJob(BaseModel):
    job_id: str
    corpus_id: str
    status: IngestStatus = IngestStatus.QUEUED
    total_files: int = 0
    completed_files: int = 0
    total_bytes: int = 0
    assets: list[AssetIngestState] = Field(default_factory=list)
    message: str = ""
    manifest: CorpusManifest | None = None

    @property
    def progress(self) -> float:
        return self.completed_files / self.total_files if self.total_files else 1.0


class ModelRoute(BaseModel):
    id: str
    label: str
    provider: str = "openai-compatible"
    base_url: str
    model: str
    api_key_env: str | None = None
    enabled: bool = True
    max_context_tokens: int | None = None
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    notes: str = ""
    capabilities: list[str] = Field(default_factory=lambda: ["text", "table"])
    max_parallel_requests: int = 4
    request_timeout_seconds: float = 120.0
    deployment: str = "cloud"
    prompt_cache: bool = False
    native_file_handles: bool = False


class RuntimeTelemetry(BaseModel):
    source: str = "unconfigured"
    lmcache_hit_rate: float | None = None
    lmcache_requested_tokens: float | None = None
    lmcache_hit_tokens: float | None = None
    vllm_prefix_hit_rate: float | None = None
    kv_cache_usage: float | None = None
    prompt_tokens_total: float | None = None
    generation_tokens_total: float | None = None
    avg_ttft_seconds: float | None = None
    raw_metrics_available: bool = False
    error: str | None = None


class ExplorerGroup(BaseModel):
    key: str
    label: str
    kind: str
    asset_path: str
    block_ids: list[str] = Field(default_factory=list)
    required_blocks: int = 0
    total_chars: int = 0
