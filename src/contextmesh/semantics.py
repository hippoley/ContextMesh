from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, Field

from .diagnostics import EvidenceStage
from .models import Evidence, EvidenceKind


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


class DecisionBundle(BaseModel):
    claims: list[SemanticEvidenceUnit] = Field(default_factory=list)
    exceptions: list[SemanticEvidenceUnit] = Field(default_factory=list)
    contradictions: list[SemanticEvidenceUnit] = Field(default_factory=list)
    requirements: list[SemanticEvidenceUnit] = Field(default_factory=list)
    facts: list[SemanticEvidenceUnit] = Field(default_factory=list)
    unresolved_authority: list[SemanticEvidenceUnit] = Field(default_factory=list)
    source_ids: set[str] = Field(default_factory=set)
    evidence_ids: set[str] = Field(default_factory=set)
    kind_counts: dict[str, int] = Field(default_factory=dict)

    @property
    def total_units(self) -> int:
        return len(self.evidence_ids)


def semantic_units_from_evidence(evidence: Iterable[Evidence]) -> list[SemanticEvidenceUnit]:
    units: list[SemanticEvidenceUnit] = []
    for item in evidence:
        for atom in item.atoms:
            atom_id = atom.id or (
                "ev_" + hashlib.sha256(
                    (
                        item.block_id
                        + "\x1f"
                        + atom.kind.value
                        + "\x1f"
                        + " ".join(atom.text.split()).lower()
                    ).encode("utf-8")
                ).hexdigest()[:20]
            )
            units.append(
                SemanticEvidenceUnit(
                    id=atom_id,
                    kind=atom.kind,
                    text=atom.text,
                    source_ids={item.block_id},
                    decisive=("decisive" in atom.tags),
                    metadata={
                        "source_path": item.source.path,
                        "locator": item.source.locator,
                        "normalized_value": atom.normalized_value,
                        "unit": atom.unit,
                        "date": atom.date,
                        "polarity": atom.polarity,
                        "confidence": atom.confidence,
                        "tags": list(atom.tags),
                    },
                )
            )
    return units


def _canonical_unit_key(unit: SemanticEvidenceUnit) -> tuple:
    normalized_value = str(unit.metadata.get("normalized_value") or "").strip().lower()
    canonical_text = " ".join(unit.text.split()).strip().lower()
    if normalized_value:
        semantic_value = normalized_value
    else:
        semantic_value = canonical_text
    return (
        unit.kind.value,
        semantic_value,
        str(unit.metadata.get("unit") or "").strip().lower(),
        str(unit.metadata.get("date") or "").strip().lower(),
        str(unit.metadata.get("polarity") or "affirm").strip().lower(),
        unit.authority_state.value,
    )


def reduce_semantic_units(
    units: Iterable[SemanticEvidenceUnit],
) -> tuple[list[SemanticEvidenceUnit], ReductionReceipt, ReductionValidation]:
    """Conservative typed reduction.

    v0.16 deliberately merges only canonical duplicates. It does not ask a model to
    decide semantic equivalence. This establishes a safe baseline before introducing
    model-proposed merges behind the monotonic reduction guard.
    """

    inputs = list(units)
    groups: dict[tuple, list[SemanticEvidenceUnit]] = {}
    order: list[tuple] = []
    for unit in inputs:
        key = _canonical_unit_key(unit)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(unit)

    outputs: list[SemanticEvidenceUnit] = []
    merged_from: dict[str, list[str]] = {}

    for key in order:
        group = groups[key]
        if len(group) == 1:
            outputs.append(group[0])
            continue

        source_ids: set[str] = set()
        for unit in group:
            source_ids.update(unit.source_ids)

        raw_id = "\x1e".join(sorted(unit.id for unit in group))
        merged_id = "red_" + hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:20]
        representative = group[0]
        merged = representative.model_copy(
            update={
                "id": merged_id,
                "source_ids": source_ids,
                "decisive": any(unit.decisive for unit in group),
                "metadata": {
                    **representative.metadata,
                    "merged_count": len(group),
                    "merged_ids": [unit.id for unit in group],
                },
            }
        )
        outputs.append(merged)
        merged_from[merged_id] = [unit.id for unit in group]

    receipt = ReductionReceipt(
        input_ids=[unit.id for unit in inputs],
        output_ids=[unit.id for unit in outputs],
        merged_from=merged_from,
        reason_codes=["canonical-duplicate-merge"],
    )
    validation = validate_monotonic_reduction(inputs, outputs, receipt)
    return outputs, receipt, validation


def build_decision_bundle(units: Iterable[SemanticEvidenceUnit]) -> DecisionBundle:
    bundle = DecisionBundle()
    counts: dict[str, int] = {}

    for unit in units:
        bundle.source_ids.update(unit.source_ids)
        bundle.evidence_ids.add(unit.id)
        counts[unit.kind.value] = counts.get(unit.kind.value, 0) + 1

        if unit.authority_state in _UNRESOLVED_AUTHORITY:
            bundle.unresolved_authority.append(unit)

        if unit.kind == EvidenceKind.EXCEPTION:
            bundle.exceptions.append(unit)
        elif unit.kind == EvidenceKind.CONTRADICTION:
            bundle.contradictions.append(unit)
        elif unit.kind == EvidenceKind.REQUIREMENT:
            bundle.requirements.append(unit)
        elif unit.kind == EvidenceKind.CLAIM:
            bundle.claims.append(unit)
        else:
            bundle.facts.append(unit)

    bundle.kind_counts = dict(sorted(counts.items()))
    return bundle


def _primary_bundle_sections(
    bundle: DecisionBundle,
) -> list[tuple[str, list[SemanticEvidenceUnit]]]:
    """Return each evidence unit exactly once in its primary epistemic category.

    unresolved_authority is a cross-cutting view, not a second copy of the same
    evidence. Authority remains explicit on every rendered unit.
    """
    sections = [
        ("EXCEPTIONS", bundle.exceptions),
        ("CONTRADICTIONS", bundle.contradictions),
        ("REQUIREMENTS", bundle.requirements),
        ("CLAIMS", bundle.claims),
        ("FACTS", bundle.facts),
    ]
    seen: set[str] = set()
    out: list[tuple[str, list[SemanticEvidenceUnit]]] = []
    for label, items in sections:
        unique = [unit for unit in items if unit.id not in seen]
        seen.update(unit.id for unit in unique)
        if unique:
            out.append((label, unique))

    unresolved_only = [
        unit for unit in bundle.unresolved_authority if unit.id not in seen
    ]
    if unresolved_only:
        out.append(("UNRESOLVED_AUTHORITY", unresolved_only))
    return out


def _provenance_ref(source_ids: set[str], *, sample_size: int = 4) -> str:
    ordered = sorted(source_ids)
    if not ordered:
        return "source_count=0"
    if len(ordered) <= sample_size:
        return f"source_count={len(ordered)} sources={','.join(ordered)}"

    canonical = "\x1e".join(ordered).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()[:20]
    sample = ",".join(ordered[:sample_size])
    return (
        f"source_count={len(ordered)} provenance_sha256={digest} "
        f"source_sample={sample}"
    )


def _decision_unit_line(category: str, unit: SemanticEvidenceUnit) -> str:
    provenance = _provenance_ref(unit.source_ids)
    return (
        f"- category={category} id={unit.id} kind={unit.kind.value} "
        f"authority={unit.authority_state.value} {provenance} :: {unit.text}"
    )


class DecisionBundleShard(BaseModel):
    index: int
    total_shards: int
    text: str
    char_count: int
    unit_ids: list[str]
    category_counts: dict[str, int] = Field(default_factory=dict)


class DecisionBundleShardSet(BaseModel):
    max_chars: int
    total_units: int
    shard_count: int
    complete: bool
    shards: list[DecisionBundleShard] = Field(default_factory=list)


def shard_decision_bundle(
    bundle: DecisionBundle,
    *,
    max_chars: int = 48_000,
) -> DecisionBundleShardSet:
    """Partition a DecisionBundle without summarizing or dropping evidence.

    Sharding solves the transport/window problem only. It deliberately does not
    invent a cross-shard verdict aggregation rule.
    """
    if max_chars < 1024:
        raise ValueError("max_chars must be >= 1024 for a decision shard")

    entries: list[tuple[str, SemanticEvidenceUnit, str]] = []
    for category, items in _primary_bundle_sections(bundle):
        for unit in items:
            entries.append((category, unit, _decision_unit_line(category, unit)))

    if not entries:
        return DecisionBundleShardSet(
            max_chars=max_chars,
            total_units=0,
            shard_count=0,
            complete=True,
            shards=[],
        )

    # Reserve enough space for deterministic shard metadata. Evidence lines are never
    # clipped: a single oversized evidence unit is an explicit error.
    header_reserve = 320
    content_budget = max_chars - header_reserve
    groups: list[list[tuple[str, SemanticEvidenceUnit, str]]] = []
    current: list[tuple[str, SemanticEvidenceUnit, str]] = []
    current_chars = 0

    for entry in entries:
        line = entry[2]
        cost = len(line) + 1
        if cost > content_budget:
            raise ValueError(
                f"evidence unit {entry[1].id} exceeds one shard budget: "
                f"line_chars={len(line)}, content_budget={content_budget}"
            )
        if current and current_chars + cost > content_budget:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(entry)
        current_chars += cost
    if current:
        groups.append(current)

    total_shards = len(groups)
    shards: list[DecisionBundleShard] = []
    all_ids: list[str] = []

    for index, group in enumerate(groups, 1):
        counts: dict[str, int] = {}
        for category, _, _ in group:
            counts[category.lower()] = counts.get(category.lower(), 0) + 1
        unit_ids = [unit.id for _, unit, _ in group]
        all_ids.extend(unit_ids)
        header = (
            f"DECISION_SHARD {index}/{total_shards} "
            f"units={len(group)} categories={dict(sorted(counts.items()))} "
            f"unresolved_authority_total={len(bundle.unresolved_authority)}"
        )
        text = "\n".join([header, *[line for _, _, line in group]])
        if len(text) > max_chars:
            raise RuntimeError(
                f"internal shard budget error: shard={index} chars={len(text)} max={max_chars}"
            )
        shards.append(
            DecisionBundleShard(
                index=index,
                total_shards=total_shards,
                text=text,
                char_count=len(text),
                unit_ids=unit_ids,
                category_counts=dict(sorted(counts.items())),
            )
        )

    expected_ids = set(bundle.evidence_ids)
    observed_ids = set(all_ids)
    complete = (
        observed_ids == expected_ids
        and len(all_ids) == len(observed_ids)
        and len(all_ids) == bundle.total_units
    )
    return DecisionBundleShardSet(
        max_chars=max_chars,
        total_units=bundle.total_units,
        shard_count=total_shards,
        complete=complete,
        shards=shards,
    )


class DecisionBundleRender(BaseModel):
    text: str
    complete: bool
    required_chars: int
    max_chars: int
    omitted_ids: list[str] = Field(default_factory=list)


def render_decision_bundle_checked(
    bundle: DecisionBundle,
    *,
    max_chars: int = 48_000,
) -> DecisionBundleRender:
    """Render the decision state while making overflow explicit.

    A final judge must never mistake a truncated DecisionBundle for a complete one.
    Until a safe typed reducer can shrink the bundle, overflow is a finalization
    blocker rather than a silent lossy transform.
    """

    sections = _primary_bundle_sections(bundle)
    all_lines = [
        (
            f"DECISION_BUNDLE total={bundle.total_units} "
            f"sources={len(bundle.source_ids)} kinds={bundle.kind_counts} "
            f"unresolved_authority={len(bundle.unresolved_authority)}"
        )
    ]
    line_ids: list[str | None] = [None]

    for label, items in sections:
        if not items:
            continue
        all_lines.append(f"\n[{label}] count={len(items)}")
        line_ids.append(None)
        for unit in items:
            all_lines.append(_decision_unit_line(label, unit))
            line_ids.append(unit.id)

    required_chars = sum(len(line) + 1 for line in all_lines)
    if required_chars <= max_chars:
        return DecisionBundleRender(
            text="\n".join(all_lines),
            complete=True,
            required_chars=required_chars,
            max_chars=max_chars,
        )

    rendered: list[str] = []
    omitted_ids: list[str] = []
    used = 0
    overflowed = False
    for line, unit_id in zip(all_lines, line_ids):
        cost = len(line) + 1
        if not overflowed and used + cost <= max_chars:
            rendered.append(line)
            used += cost
            continue
        overflowed = True
        if unit_id is not None:
            omitted_ids.append(unit_id)

    # Once overflow begins, later units are intentionally not substituted into the
    # final decision state. The preview is diagnostic only; callers must check
    # complete before using it for judgment.
    return DecisionBundleRender(
        text="\n".join(rendered),
        complete=False,
        required_chars=required_chars,
        max_chars=max_chars,
        omitted_ids=omitted_ids,
    )


def render_decision_bundle(bundle: DecisionBundle, *, max_chars: int = 48_000) -> str:
    """Compatibility helper for non-judgment display paths.

    Callers that make a final decision must use render_decision_bundle_checked and
    require complete=true.
    """
    return render_decision_bundle_checked(bundle, max_chars=max_chars).text
