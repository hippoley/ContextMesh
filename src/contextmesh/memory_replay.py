from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, Field, computed_field


class MemoryFact(BaseModel):
    id: str
    subject: str
    predicate: str
    value: str
    event_time: datetime
    observed_time: datetime | None = None
    verified: bool = False
    status: str = "active"  # active | superseded | refuted | contested
    superseded_by: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source: str = ""
    transient: bool = False

    @computed_field
    @property
    def key(self) -> str:
        return f"{self.subject}:{self.predicate}"


class MemoryReplayCase(BaseModel):
    id: str
    title: str
    now: datetime
    query: str
    expected_fact_id: str
    facts: list[MemoryFact]
    reality_sources: list[str] = Field(default_factory=list)


class MemoryPolicyDecision(BaseModel):
    policy: str
    case_id: str
    selected_fact_id: str | None
    selected_value: str | None
    expected_fact_id: str
    correct: bool
    considered_fact_ids: list[str]
    excluded_fact_ids: list[str]
    reason: str
    audit_preserved: bool


class MemoryReplayReport(BaseModel):
    decisions: list[MemoryPolicyDecision]

    @computed_field
    @property
    def by_policy(self) -> dict[str, dict[str, int | float]]:
        out: dict[str, dict[str, int | float]] = {}
        for policy in sorted({x.policy for x in self.decisions}):
            rows = [x for x in self.decisions if x.policy == policy]
            out[policy] = {
                "cases": len(rows),
                "correct": sum(1 for x in rows if x.correct),
                "accuracy": (
                    sum(1 for x in rows if x.correct) / len(rows) if rows else 0.0
                ),
                "audit_preserved": sum(1 for x in rows if x.audit_preserved),
            }
        return out

    def to_markdown(self) -> str:
        lines = [
            "# Temporal Memory Reality Replay",
            "",
            "| Case | Policy | Selected | Expected | Correct | Audit preserved |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in self.decisions:
            lines.append(
                f"| {row.case_id} | {row.policy} | {row.selected_fact_id or 'none'} | "
                f"{row.expected_fact_id} | {'yes' if row.correct else 'no'} | "
                f"{'yes' if row.audit_preserved else 'no'} |"
            )
        lines += ["", "## Aggregate", "", str(self.by_policy)]
        return "\n".join(lines)


class MemoryPolicy(Protocol):
    name: str

    def decide(self, case: MemoryReplayCase) -> MemoryPolicyDecision: ...


def _ordered(facts: list[MemoryFact]) -> list[MemoryFact]:
    return sorted(
        facts,
        key=lambda x: (x.event_time, x.observed_time or x.event_time, x.id),
    )


def _current_by_interval(fact: MemoryFact, now: datetime) -> bool:
    start = fact.valid_from or fact.event_time
    if now < start:
        return False
    if fact.valid_until is not None and now >= fact.valid_until:
        return False
    return True


class LastWriteWinsPolicy:
    """Deliberately naive baseline: newest active-looking fact wins."""

    name = "last-write-wins"

    def decide(self, case: MemoryReplayCase) -> MemoryPolicyDecision:
        ordered = _ordered(case.facts)
        candidates = [x for x in ordered if x.status not in {"superseded", "refuted"}]
        selected = candidates[-1] if candidates else None
        return MemoryPolicyDecision(
            policy=self.name,
            case_id=case.id,
            selected_fact_id=selected.id if selected else None,
            selected_value=selected.value if selected else None,
            expected_fact_id=case.expected_fact_id,
            correct=bool(selected and selected.id == case.expected_fact_id),
            considered_fact_ids=[x.id for x in candidates],
            excluded_fact_ids=[x.id for x in ordered if x not in candidates],
            reason="newest non-closed memory wins; verification and validity intervals are ignored",
            audit_preserved=True,
        )


class DestructiveNewestWinsPolicy:
    """Models a hygiene pass that deletes/merges history and retains only the newest row."""

    name = "destructive-newest-wins"

    def decide(self, case: MemoryReplayCase) -> MemoryPolicyDecision:
        ordered = _ordered(case.facts)
        selected = ordered[-1] if ordered else None
        return MemoryPolicyDecision(
            policy=self.name,
            case_id=case.id,
            selected_fact_id=selected.id if selected else None,
            selected_value=selected.value if selected else None,
            expected_fact_id=case.expected_fact_id,
            correct=bool(selected and selected.id == case.expected_fact_id),
            considered_fact_ids=[selected.id] if selected else [],
            excluded_fact_ids=[x.id for x in ordered[:-1]],
            reason="compaction retained only the newest row; superseded/refuted history is no longer inspectable",
            audit_preserved=len(ordered) <= 1,
        )


class VerifiedSupersessionPolicy:
    """Reference policy derived from the issue's community consensus.

    This is not claimed to be Mem0's current behavior. It demonstrates a
    falsifiable policy: explicit lifecycle + validity + verification outrank
    raw recency. Unverified conflicts remain contested instead of silently
    superseding a verified fact.
    """

    name = "verified-supersession"

    def decide(self, case: MemoryReplayCase) -> MemoryPolicyDecision:
        ordered = _ordered(case.facts)
        closed = {"superseded", "refuted"}
        eligible = [
            x for x in ordered
            if x.status not in closed and _current_by_interval(x, case.now)
        ]

        verified = [x for x in eligible if x.verified and x.status != "contested"]
        if verified:
            selected = verified[-1]
            reason = "latest verified fact within its validity interval wins; closed/expired/unverified conflicts remain non-authoritative"
        else:
            non_contested = [x for x in eligible if x.status != "contested"]
            selected = non_contested[-1] if non_contested else None
            reason = "no verified current fact exists; fall back only to non-contested current evidence"

        considered = {x.id for x in eligible}
        return MemoryPolicyDecision(
            policy=self.name,
            case_id=case.id,
            selected_fact_id=selected.id if selected else None,
            selected_value=selected.value if selected else None,
            expected_fact_id=case.expected_fact_id,
            correct=bool(selected and selected.id == case.expected_fact_id),
            considered_fact_ids=[x.id for x in eligible],
            excluded_fact_ids=[x.id for x in ordered if x.id not in considered],
            reason=reason,
            audit_preserved=True,
        )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def issue_derived_memory_cases() -> list[MemoryReplayCase]:
    sources = ["https://github.com/mem0ai/mem0/issues/5352"]

    transient_override = MemoryReplayCase(
        id="transient-newer-is-not-truth",
        title="Newer transient observation must not overwrite verified configuration",
        now=_dt("2026-09-24T12:00:00"),
        query="What database port should the agent use now?",
        expected_fact_id="db-port-stable",
        facts=[
            MemoryFact(
                id="db-port-stable",
                subject="database",
                predicate="port",
                value="5432",
                event_time=_dt("2026-09-01T09:00:00"),
                verified=True,
                source="signed production configuration",
            ),
            MemoryFact(
                id="db-port-transient",
                subject="database",
                predicate="port",
                value="6543",
                event_time=_dt("2026-09-23T18:00:00"),
                verified=False,
                status="contested",
                transient=True,
                source="one failed connection attempt / transient runtime observation",
            ),
        ],
        reality_sources=sources,
    )

    expired_override = MemoryReplayCase(
        id="temporary-override-expired",
        title="Expired emergency override must not remain authoritative",
        now=_dt("2026-09-24T12:00:00"),
        query="Which region is authoritative now?",
        expected_fact_id="region-primary",
        facts=[
            MemoryFact(
                id="region-primary",
                subject="deployment",
                predicate="primary_region",
                value="us-east-1",
                event_time=_dt("2026-08-01T00:00:00"),
                verified=True,
                source="deployment policy",
            ),
            MemoryFact(
                id="region-emergency",
                subject="deployment",
                predicate="primary_region",
                value="us-west-2",
                event_time=_dt("2026-09-20T04:00:00"),
                valid_from=_dt("2026-09-20T04:00:00"),
                valid_until=_dt("2026-09-20T10:00:00"),
                verified=True,
                transient=True,
                source="six-hour incident failover",
            ),
        ],
        reality_sources=sources,
    )

    verified_preference_change = MemoryReplayCase(
        id="verified-preference-change",
        title="A real verified change should supersede the prior preference",
        now=_dt("2026-09-24T12:00:00"),
        query="Which theme does the user currently prefer?",
        expected_fact_id="theme-light",
        facts=[
            MemoryFact(
                id="theme-dark",
                subject="user",
                predicate="theme",
                value="dark",
                event_time=_dt("2026-08-10T10:00:00"),
                verified=True,
                status="superseded",
                superseded_by="theme-light",
                source="explicit user preference",
            ),
            MemoryFact(
                id="theme-light",
                subject="user",
                predicate="theme",
                value="light",
                event_time=_dt("2026-09-12T14:00:00"),
                verified=True,
                source="explicit user preference change",
            ),
        ],
        reality_sources=sources,
    )

    rollback_after_bad_write = MemoryReplayCase(
        id="refuted-latest-write",
        title="A later refuted memory must not shadow the earlier verified truth",
        now=_dt("2026-09-24T12:00:00"),
        query="What is the production status color?",
        expected_fact_id="status-green",
        facts=[
            MemoryFact(
                id="status-green",
                subject="production",
                predicate="status_color",
                value="green",
                event_time=_dt("2026-09-10T09:00:00"),
                verified=True,
                source="monitoring baseline",
            ),
            MemoryFact(
                id="status-red-echo",
                subject="production",
                predicate="status_color",
                value="red",
                event_time=_dt("2026-09-23T09:00:00"),
                verified=False,
                status="refuted",
                transient=True,
                source="assistant echo of a stale incident message",
            ),
        ],
        reality_sources=sources,
    )

    return [
        transient_override,
        expired_override,
        verified_preference_change,
        rollback_after_bad_write,
    ]


def run_memory_replay(
    *,
    policies: list[MemoryPolicy] | None = None,
    cases: list[MemoryReplayCase] | None = None,
) -> MemoryReplayReport:
    policies = policies or [
        LastWriteWinsPolicy(),
        DestructiveNewestWinsPolicy(),
        VerifiedSupersessionPolicy(),
    ]
    cases = cases or issue_derived_memory_cases()
    decisions: list[MemoryPolicyDecision] = []
    for case in cases:
        for policy in policies:
            decisions.append(policy.decide(case))
    return MemoryReplayReport(decisions=decisions)
