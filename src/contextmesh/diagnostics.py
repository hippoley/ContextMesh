from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class EvidenceStage(str, Enum):
    INGESTED = "ingested"
    STORED = "stored"
    RETRIEVED = "retrieved"
    ELIGIBLE = "eligible"
    RENDERED = "rendered"
    MODEL_VISIBLE = "model-visible"
    AUTHORITY = "authority"
    JUDGED = "judged"


class EvidenceDisposition(str, Enum):
    PRESENT = "present"
    EXCLUDED = "excluded"
    TRUNCATED = "truncated"
    MISSING = "missing"
    UNKNOWN = "unknown"
    FAILED = "failed"


class EvidenceFailureClass(str, Enum):
    NONE = "none"
    INGEST_LOSS = "ingest-loss"
    RETRIEVAL_MISS = "retrieval-miss"
    ELIGIBILITY_LOSS = "eligibility-loss"
    TRANSPORT_VISIBILITY_LOSS = "transport-visibility-loss"
    AUTHORITY_UNRESOLVED = "authority-unresolved"
    JUDGE_FAILURE = "judge-failure"
    UNKNOWN = "unknown"


class EvidenceStageRecord(BaseModel):
    stage: EvidenceStage
    disposition: EvidenceDisposition
    reason: str = ""
    rank: int | None = None
    source_bytes: int | None = None
    visible_bytes: int | None = None
    visible_ranges: list[list[int]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def present(self) -> bool:
        return self.disposition in {EvidenceDisposition.PRESENT, EvidenceDisposition.TRUNCATED}

    @computed_field
    @property
    def byte_visibility_ratio(self) -> float | None:
        if self.source_bytes is None or self.visible_bytes is None:
            return None
        if self.source_bytes == 0:
            return 1.0
        return max(0.0, min(1.0, self.visible_bytes / self.source_bytes))


class EvidenceLifecycleTrace(BaseModel):
    source_id: str
    decisive: bool = False
    stages: list[EvidenceStageRecord] = Field(default_factory=list)
    failure_class: EvidenceFailureClass = EvidenceFailureClass.NONE

    def stage(self, name: EvidenceStage) -> EvidenceStageRecord | None:
        return next((x for x in self.stages if x.stage == name), None)

    @computed_field
    @property
    def first_non_present_stage(self) -> str | None:
        for item in self.stages:
            if item.disposition not in {EvidenceDisposition.PRESENT, EvidenceDisposition.TRUNCATED}:
                return item.stage.value
            if (
                item.stage == EvidenceStage.MODEL_VISIBLE
                and item.disposition == EvidenceDisposition.TRUNCATED
            ):
                return item.stage.value
        return None

    @computed_field
    @property
    def model_visible_ratio(self) -> float | None:
        item = self.stage(EvidenceStage.MODEL_VISIBLE)
        return item.byte_visibility_ratio if item else None


def classify_evidence_failure(
    *,
    ingested: bool = True,
    stored: bool = True,
    rank: int | None,
    eligible: bool,
    rendered: bool,
    semantic_visible: bool,
    authority_resolved: bool = True,
) -> EvidenceFailureClass:
    if not ingested or not stored:
        return EvidenceFailureClass.INGEST_LOSS
    if rank is None:
        return EvidenceFailureClass.RETRIEVAL_MISS
    if not eligible:
        return EvidenceFailureClass.ELIGIBILITY_LOSS
    if not rendered or not semantic_visible:
        return EvidenceFailureClass.TRANSPORT_VISIBILITY_LOSS
    if not authority_resolved:
        return EvidenceFailureClass.AUTHORITY_UNRESOLVED
    return EvidenceFailureClass.NONE


def build_probe_lifecycle(
    *,
    source_id: str,
    decisive: bool,
    rank: int | None,
    selected: bool,
    source_bytes: int,
    visible_bytes: int,
    visible_ranges: list[list[int]],
    semantic_visible: bool,
    live_judged: bool | None = None,
) -> EvidenceLifecycleTrace:
    rendered = bool(selected and visible_bytes > 0)
    failure_class = classify_evidence_failure(
        rank=rank,
        eligible=selected,
        rendered=rendered,
        semantic_visible=semantic_visible,
    )

    if rank is None:
        retrieved_disp = EvidenceDisposition.MISSING
        retrieved_reason = "source absent from measured retrieval/ranking output"
    else:
        retrieved_disp = EvidenceDisposition.PRESENT
        retrieved_reason = "source present in measured ranking"

    eligible_disp = EvidenceDisposition.PRESENT if selected else EvidenceDisposition.EXCLUDED
    eligible_reason = (
        "source remained eligible for downstream evidence"
        if selected
        else "source was removed by the backend eligibility/cutoff policy"
    )

    if not selected:
        rendered_disp = EvidenceDisposition.MISSING
        model_disp = EvidenceDisposition.MISSING
        rendered_reason = "source was not eligible, so it was never rendered"
        model_reason = "source was not eligible, so no model-visible content exists"
    else:
        rendered_disp = (
            EvidenceDisposition.PRESENT
            if visible_bytes >= source_bytes
            else EvidenceDisposition.TRUNCATED
        )
        rendered_reason = (
            "full source bytes were exposed by the transport"
            if visible_bytes >= source_bytes
            else "transport exposed only a subset of source bytes"
        )
        if semantic_visible:
            model_disp = (
                EvidenceDisposition.PRESENT
                if visible_bytes >= source_bytes
                else EvidenceDisposition.TRUNCATED
            )
            model_reason = "decisive semantics survived into model-visible content"
        else:
            model_disp = EvidenceDisposition.TRUNCATED
            model_reason = "source was selected, but decisive semantics were absent from model-visible content"

    stages = [
        EvidenceStageRecord(
            stage=EvidenceStage.INGESTED,
            disposition=EvidenceDisposition.PRESENT,
            reason="source exists in the benchmark corpus",
            source_bytes=source_bytes,
            visible_bytes=source_bytes,
            visible_ranges=[[0, source_bytes]],
        ),
        EvidenceStageRecord(
            stage=EvidenceStage.STORED,
            disposition=EvidenceDisposition.PRESENT,
            reason="source is addressable by the benchmark backend",
            source_bytes=source_bytes,
            visible_bytes=source_bytes,
            visible_ranges=[[0, source_bytes]],
        ),
        EvidenceStageRecord(
            stage=EvidenceStage.RETRIEVED,
            disposition=retrieved_disp,
            reason=retrieved_reason,
            rank=rank,
        ),
        EvidenceStageRecord(
            stage=EvidenceStage.ELIGIBLE,
            disposition=eligible_disp,
            reason=eligible_reason,
            rank=rank,
        ),
        EvidenceStageRecord(
            stage=EvidenceStage.RENDERED,
            disposition=rendered_disp,
            reason=rendered_reason,
            source_bytes=source_bytes,
            visible_bytes=visible_bytes,
            visible_ranges=visible_ranges,
        ),
        EvidenceStageRecord(
            stage=EvidenceStage.MODEL_VISIBLE,
            disposition=model_disp,
            reason=model_reason,
            source_bytes=source_bytes,
            visible_bytes=visible_bytes,
            visible_ranges=visible_ranges,
        ),
    ]
    if live_judged is not None:
        stages.append(
            EvidenceStageRecord(
                stage=EvidenceStage.JUDGED,
                disposition=(
                    EvidenceDisposition.PRESENT if live_judged else EvidenceDisposition.FAILED
                ),
                reason=(
                    "live judge completed over backend-visible evidence"
                    if live_judged
                    else "live judge did not complete successfully"
                ),
            )
        )

    return EvidenceLifecycleTrace(
        source_id=source_id,
        decisive=decisive,
        stages=stages,
        failure_class=failure_class,
    )



def build_authority_lifecycle(
    *,
    source_id: str,
    status: str,
    verified: bool,
    selected_as_authority: bool,
    reason: str,
    decisive: bool = True,
) -> EvidenceLifecycleTrace:
    """Build a compact lifecycle trace for a memory/fact authority decision.

    This starts after storage/retrieval: the fact exists and is available, but
    the policy still needs to decide whether it is authoritative now.
    """
    normalized = (status or "").strip().lower()
    closed = normalized in {"superseded", "refuted", "expired"}
    contested = normalized in {"contested", "review"}

    if selected_as_authority:
        authority_disp = EvidenceDisposition.PRESENT
        failure = EvidenceFailureClass.NONE
    elif closed:
        authority_disp = EvidenceDisposition.EXCLUDED
        failure = EvidenceFailureClass.NONE
    elif contested or not verified:
        authority_disp = EvidenceDisposition.UNKNOWN
        failure = EvidenceFailureClass.AUTHORITY_UNRESOLVED
    else:
        authority_disp = EvidenceDisposition.EXCLUDED
        failure = EvidenceFailureClass.NONE

    stages = [
        EvidenceStageRecord(
            stage=EvidenceStage.INGESTED,
            disposition=EvidenceDisposition.PRESENT,
            reason="fact entered the memory/evidence history",
        ),
        EvidenceStageRecord(
            stage=EvidenceStage.STORED,
            disposition=EvidenceDisposition.PRESENT,
            reason="fact remains preserved and auditable",
        ),
        EvidenceStageRecord(
            stage=EvidenceStage.RETRIEVED,
            disposition=EvidenceDisposition.PRESENT,
            reason="fact is available to the authority policy",
        ),
        EvidenceStageRecord(
            stage=EvidenceStage.AUTHORITY,
            disposition=authority_disp,
            reason=reason,
            metadata={
                "status": normalized or status,
                "verified": verified,
                "selected_as_authority": selected_as_authority,
            },
        ),
    ]
    return EvidenceLifecycleTrace(
        source_id=source_id,
        decisive=decisive,
        stages=stages,
        failure_class=failure,
    )
