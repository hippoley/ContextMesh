from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, Field

from .diagnostics import EvidenceStage
from .models import EvidenceKind


class ExecutionMode(str, Enum):
    RETRIEVAL = "retrieval"
    HIERARCHICAL_SUMMARY = "hierarchical-summary"
    FULL_COVERAGE = "full-coverage"
    EXHAUSTIVE_EXTRACTION = "exhaustive-extraction"
    AUTHORITY_RESOLUTION = "authority-resolution"


class TransitionAction(str, Enum):
    PRESERVE = "preserve"
    TRANSFORM = "transform"
    EXCLUDE = "exclude"
    MERGE = "merge"
    SUPERSEDE = "supersede"
    BLOCK = "block"
    FAIL = "fail"


class AuthorityState(str, Enum):
    ACTIVE = "active"
    CONTESTED = "contested"
    SUPERSEDED = "superseded"
    REFUTED = "refuted"
    EXPIRED = "expired"
    UNRESOLVED = "unresolved"


class ExecutionContract(BaseModel):
    """Task-level semantics for what must be true before a result is finalizable.

    The contract deliberately separates scheduling from eligibility. A retrieval
    task may permit a selected subset, while a full-coverage task requires every
    declared source to reach the required execution stages.
    """

    mode: ExecutionMode
    required_source_ids: set[str] = Field(default_factory=set)
    required_stages: set[EvidenceStage] = Field(default_factory=set)
    require_authority_resolution: bool = False
    allow_failed_required_sources: bool = False

    @classmethod
    def retrieval(cls) -> "ExecutionContract":
        return cls(mode=ExecutionMode.RETRIEVAL)

    @classmethod
    def full_coverage(cls, source_ids: Iterable[str]) -> "ExecutionContract":
        return cls(
            mode=ExecutionMode.FULL_COVERAGE,
            required_source_ids=set(source_ids),
            required_stages={
                EvidenceStage.INGESTED,
                EvidenceStage.STORED,
                EvidenceStage.ELIGIBLE,
                EvidenceStage.MODEL_VISIBLE,
                EvidenceStage.INSPECTED,
            },
        )

    @classmethod
    def authority_resolution(cls, source_ids: Iterable[str]) -> "ExecutionContract":
        return cls(
            mode=ExecutionMode.AUTHORITY_RESOLUTION,
            required_source_ids=set(source_ids),
            required_stages={
                EvidenceStage.INGESTED,
                EvidenceStage.STORED,
                EvidenceStage.RETRIEVED,
                EvidenceStage.AUTHORITY,
            },
            require_authority_resolution=True,
        )


class CoverageSnapshot(BaseModel):
    """Multi-stage coverage accounting.

    A scalar coverage number cannot distinguish not-retrieved from retrieved but
    not model-visible, or visible but never inspected. This snapshot keeps those
    states separate.
    """

    stage_subjects: dict[EvidenceStage, set[str]] = Field(default_factory=dict)
    failed_subjects: set[str] = Field(default_factory=set)
    unresolved_authority_subjects: set[str] = Field(default_factory=set)

    def mark(self, subject_id: str, stage: EvidenceStage) -> None:
        self.stage_subjects.setdefault(stage, set()).add(subject_id)

    def reached(self, subject_id: str, stage: EvidenceStage) -> bool:
        return subject_id in self.stage_subjects.get(stage, set())

    def coverage(self, stage: EvidenceStage, required: Iterable[str]) -> float:
        required_set = set(required)
        if not required_set:
            return 1.0
        reached = self.stage_subjects.get(stage, set())
        return len(required_set & reached) / len(required_set)

    def missing(self, stage: EvidenceStage, required: Iterable[str]) -> set[str]:
        return set(required) - self.stage_subjects.get(stage, set())

    def finalization_blockers(self, contract: ExecutionContract) -> list[str]:
        blockers: list[str] = []
        required = contract.required_source_ids

        for stage in sorted(contract.required_stages, key=lambda x: x.value):
            missing = self.missing(stage, required)
            if missing:
                blockers.append(f"{stage.value}:missing={len(missing)}")

        failed_required = required & self.failed_subjects
        if failed_required and not contract.allow_failed_required_sources:
            blockers.append(f"failed-required={len(failed_required)}")

        if contract.require_authority_resolution:
            unresolved = required & self.unresolved_authority_subjects
            if unresolved:
                blockers.append(f"authority-unresolved={len(unresolved)}")

        return blockers

    def can_finalize(self, contract: ExecutionContract) -> bool:
        return not self.finalization_blockers(contract)


class TransitionReceipt(BaseModel):
    """Append-only receipt for one semantic state transition."""

    sequence: int
    subject_id: str
    from_stage: EvidenceStage | None = None
    to_stage: EvidenceStage
    action: TransitionAction = TransitionAction.PRESERVE
    reason_codes: list[str] = Field(default_factory=list)
    policy_id: str | None = None
    policy_version: str | None = None
    input_sha256: str | None = None
    output_sha256: str | None = None
    lossy: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str | None = None
    receipt_hash: str

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude={"receipt_hash"}, mode="json")

    def verify_hash(self) -> bool:
        raw = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest() == self.receipt_hash


class TransitionLedger(BaseModel):
    """Tamper-evident transition ledger.

    This is not a blockchain and is not intended as a cryptographic trust anchor.
    The hash chain makes accidental or replayed mutation of an execution trace
    machine-detectable.
    """

    receipts: list[TransitionReceipt] = Field(default_factory=list)

    def append(
        self,
        *,
        subject_id: str,
        to_stage: EvidenceStage,
        from_stage: EvidenceStage | None = None,
        action: TransitionAction = TransitionAction.PRESERVE,
        reason_codes: Iterable[str] = (),
        policy_id: str | None = None,
        policy_version: str | None = None,
        input_sha256: str | None = None,
        output_sha256: str | None = None,
        lossy: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TransitionReceipt:
        previous_hash = self.receipts[-1].receipt_hash if self.receipts else None
        payload = {
            "sequence": len(self.receipts) + 1,
            "subject_id": subject_id,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "action": action,
            "reason_codes": list(reason_codes),
            "policy_id": policy_id,
            "policy_version": policy_version,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "lossy": lossy,
            "metadata": metadata or {},
            "previous_hash": previous_hash,
        }
        canonical = TransitionReceipt(
            **payload,
            receipt_hash="",
        ).model_dump(exclude={"receipt_hash"}, mode="json")
        raw = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        receipt = TransitionReceipt(
            **payload,
            receipt_hash=hashlib.sha256(raw).hexdigest(),
        )
        self.receipts.append(receipt)
        return receipt

    def verify_chain(self) -> bool:
        previous: str | None = None
        for index, receipt in enumerate(self.receipts, 1):
            if receipt.sequence != index:
                return False
            if receipt.previous_hash != previous:
                return False
            if not receipt.verify_hash():
                return False
            previous = receipt.receipt_hash
        return True


class SemanticEvidenceUnit(BaseModel):
    """Reduction-safe evidence representation.

    source_ids carry provenance, while kind and authority_state preserve epistemic
    diversity that free-form summaries can accidentally erase.
    """

    id: str
    kind: EvidenceKind
    text: str
    source_ids: set[str] = Field(default_factory=set)
    authority_state: AuthorityState = AuthorityState.ACTIVE
    decisive: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReductionReceipt(BaseModel):
    input_ids: list[str]
    output_ids: list[str]
    merged_from: dict[str, list[str]] = Field(default_factory=dict)
    dropped_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class ReductionValidation(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_CRITICAL_KINDS = {
    EvidenceKind.EXCEPTION,
    EvidenceKind.CONTRADICTION,
    EvidenceKind.REQUIREMENT,
}
_UNRESOLVED_AUTHORITY = {
    AuthorityState.CONTESTED,
    AuthorityState.UNRESOLVED,
}


def validate_monotonic_reduction(
    inputs: Iterable[SemanticEvidenceUnit],
    outputs: Iterable[SemanticEvidenceUnit],
    receipt: ReductionReceipt,
) -> ReductionValidation:
    """Verify that compression removed redundancy, not epistemic diversity.

    Critical, decisive, and unresolved inputs may be preserved directly or merged
    into an output that keeps the same evidence kind, authority uncertainty, and
    provenance. They may not silently disappear into a generic claim.
    """

    input_by_id = {x.id: x for x in inputs}
    output_by_id = {x.id: x for x in outputs}
    errors: list[str] = []
    warnings: list[str] = []

    declared_inputs = set(receipt.input_ids)
    declared_outputs = set(receipt.output_ids)
    if declared_inputs != set(input_by_id):
        errors.append("receipt input_ids do not match reduction inputs")
    if declared_outputs != set(output_by_id):
        errors.append("receipt output_ids do not match reduction outputs")

    merged_target: dict[str, str] = {}
    for output_id, source_ids in receipt.merged_from.items():
        if output_id not in output_by_id:
            errors.append(f"merge target missing from outputs: {output_id}")
            continue
        for source_id in source_ids:
            if source_id in merged_target:
                errors.append(f"input merged more than once: {source_id}")
            merged_target[source_id] = output_id

    dropped = set(receipt.dropped_ids)
    for source_id in dropped:
        if source_id not in input_by_id:
            errors.append(f"dropped id not present in inputs: {source_id}")

    for unit in input_by_id.values():
        critical = unit.kind in _CRITICAL_KINDS or unit.decisive
        unresolved = unit.authority_state in _UNRESOLVED_AUTHORITY

        if unit.id in output_by_id:
            out = output_by_id[unit.id]
            if critical and out.kind != unit.kind:
                errors.append(
                    f"critical evidence changed kind: {unit.id} {unit.kind.value}->{out.kind.value}"
                )
            if unresolved and out.authority_state not in _UNRESOLVED_AUTHORITY:
                errors.append(f"unresolved authority was silently resolved: {unit.id}")
            continue

        target_id = merged_target.get(unit.id)
        if target_id:
            out = output_by_id[target_id]
            if critical and out.kind != unit.kind:
                errors.append(
                    f"critical evidence merged into different kind: {unit.id}->{target_id}"
                )
            if unresolved and out.authority_state not in _UNRESOLVED_AUTHORITY:
                errors.append(
                    f"unresolved authority merged into resolved output: {unit.id}->{target_id}"
                )
            if not unit.source_ids.issubset(out.source_ids):
                errors.append(f"provenance lost during merge: {unit.id}->{target_id}")
            continue

        if unit.id in dropped:
            if critical:
                errors.append(f"critical/decisive evidence dropped: {unit.id}")
            elif unresolved:
                errors.append(f"unresolved-authority evidence dropped: {unit.id}")
            else:
                warnings.append(f"non-critical evidence dropped: {unit.id}")
            continue

        errors.append(f"input has no reduction disposition: {unit.id}")

    return ReductionValidation(ok=not errors, errors=errors, warnings=warnings)
