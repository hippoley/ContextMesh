from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from .memory_replay import (
    MemoryFact,
    MemoryReplayCase,
    VerifiedSupersessionPolicy,
    issue_derived_memory_cases,
)

SUPERSESSION_DEPTH_SWEEP = (0, 5, 10, 20, 51)
DEFAULT_CANDIDATE_BUDGET = 10

FailureMode = Literal["none", "candidate-visibility", "authority-policy"]


class AuthorityReplayObservation(BaseModel):
    scenario_id: str
    scenario_title: str
    superseded_history_depth: int
    candidate_budget: int
    authoritative_fact_id: str
    authoritative_stored: bool
    authoritative_candidate_rank: int | None
    authoritative_survives_budget: bool
    authoritative_eligible_bounded: bool
    oracle_selected_fact_id: str | None
    bounded_selected_fact_id: str | None
    oracle_correct: bool
    bounded_correct: bool
    failure_mode: FailureMode
    eligible_bounded_fact_ids: list[str]
    eligible_oracle_fact_ids: list[str]
    history_recoverable: bool
    dual_current_eligible_risk_bounded: bool
    reality_sources: list[str] = Field(default_factory=list)


class AuthorityReplayReport(BaseModel):
    kind: str = "contextmesh-authority-replay-probe"
    candidate_budget: int
    depth_sweep: list[int]
    policy: str = VerifiedSupersessionPolicy.name
    observations: list[AuthorityReplayObservation]

    @computed_field
    @property
    def first_candidate_visibility_failure_by_scenario(self) -> dict[str, int | None]:
        out: dict[str, int | None] = {}
        for scenario_id in sorted({x.scenario_id for x in self.observations}):
            failures = [
                x.superseded_history_depth
                for x in self.observations
                if x.scenario_id == scenario_id
                and x.failure_mode == "candidate-visibility"
            ]
            out[scenario_id] = min(failures) if failures else None
        return out

    def to_markdown(self) -> str:
        lines = [
            "# Authority replay under supersession depth and candidate truncation",
            "",
            f"Policy: `{self.policy}` · candidate budget: **{self.candidate_budget}**",
            "",
            "| Scenario | Depth | Stored | Cand. rank | In budget | Bounded OK | Oracle OK | Failure mode |",
            "| --- | ---: | --- | ---: | --- | --- | --- | --- |",
        ]
        for row in self.observations:
            depth_label = "50+" if row.superseded_history_depth == 51 else str(row.superseded_history_depth)
            rank = str(row.authoritative_candidate_rank) if row.authoritative_candidate_rank else "—"
            lines.append(
                f"| {row.scenario_id} | {depth_label} | "
                f"{'yes' if row.authoritative_stored else 'no'} | {rank} | "
                f"{'yes' if row.authoritative_survives_budget else 'no'} | "
                f"{'yes' if row.bounded_correct else 'no'} | "
                f"{'yes' if row.oracle_correct else 'no'} | {row.failure_mode} |"
            )
        lines += [
            "",
            "## First candidate-visibility failure depth",
            "",
            str(self.first_candidate_visibility_failure_by_scenario),
        ]
        return "\n".join(lines)


def _retrieval_rank(facts: list[MemoryFact]) -> list[MemoryFact]:
    return sorted(
        facts,
        key=lambda x: (x.event_time, x.observed_time or x.event_time, x.id),
        reverse=True,
    )


def _depth_fillers(case: MemoryReplayCase, depth: int) -> list[MemoryFact]:
    if depth <= 0:
        return []
    anchor = next(
        (f for f in case.facts if f.id == case.expected_fact_id),
        max(case.facts, key=lambda x: x.event_time),
    )
    latest = max(case.facts, key=lambda x: x.event_time)
    start = anchor.event_time + timedelta(hours=1)
    end = latest.event_time - timedelta(hours=1)
    if end <= start:
        end = start + timedelta(hours=depth)
    step = (end - start) / max(depth, 1)
    fillers: list[MemoryFact] = []
    for index in range(depth):
        event_time = start + step * index
        fillers.append(
            MemoryFact(
                id=f"superseded-depth-{depth}-{index}",
                subject=anchor.subject,
                predicate=anchor.predicate,
                value=f"historical-{depth}-{index}",
                event_time=event_time,
                verified=True,
                status="superseded",
                superseded_by=case.expected_fact_id,
                source="synthetic superseded history for rank-depth pressure",
            )
        )
    return fillers


def case_at_depth(case: MemoryReplayCase, depth: int) -> MemoryReplayCase:
    fillers = _depth_fillers(case, depth)
    return case.model_copy(update={"facts": [*case.facts, *fillers]})


def _eligible_ids(case: MemoryReplayCase, policy: VerifiedSupersessionPolicy) -> list[str]:
    decision = policy.decide(case)
    return list(decision.considered_fact_ids)


def _dual_current_eligible_risk(case: MemoryReplayCase, eligible_ids: list[str]) -> bool:
    if not eligible_ids:
        return False
    by_key: dict[str, list[MemoryFact]] = {}
    for fact in case.facts:
        if fact.id not in eligible_ids:
            continue
        by_key.setdefault(fact.key, []).append(fact)
    for group in by_key.values():
        active_like = [x for x in group if x.status not in {"superseded", "refuted"}]
        if len(active_like) > 1:
            return True
    return False


def _classify_failure(oracle_correct: bool, bounded_correct: bool) -> FailureMode:
    if bounded_correct:
        return "none"
    if oracle_correct:
        return "candidate-visibility"
    return "authority-policy"


def observe_case(
    case: MemoryReplayCase,
    *,
    depth: int,
    candidate_budget: int,
    policy: VerifiedSupersessionPolicy | None = None,
) -> AuthorityReplayObservation:
    policy = policy or VerifiedSupersessionPolicy()
    expanded = case_at_depth(case, depth)
    ranked = _retrieval_rank(expanded.facts)
    ranks = {fact.id: index + 1 for index, fact in enumerate(ranked)}
    authoritative_rank = ranks.get(case.expected_fact_id)
    survives = bool(
        authoritative_rank is not None and authoritative_rank <= candidate_budget
    )
    candidates = ranked[:candidate_budget]
    bounded_case = expanded.model_copy(update={"facts": candidates})

    oracle = policy.decide(expanded)
    bounded = policy.decide(bounded_case)
    eligible_bounded = _eligible_ids(bounded_case, policy)
    eligible_oracle = _eligible_ids(expanded, policy)

    return AuthorityReplayObservation(
        scenario_id=case.id,
        scenario_title=case.title,
        superseded_history_depth=depth,
        candidate_budget=candidate_budget,
        authoritative_fact_id=case.expected_fact_id,
        authoritative_stored=any(x.id == case.expected_fact_id for x in expanded.facts),
        authoritative_candidate_rank=authoritative_rank,
        authoritative_survives_budget=survives,
        authoritative_eligible_bounded=case.expected_fact_id in eligible_bounded,
        oracle_selected_fact_id=oracle.selected_fact_id,
        bounded_selected_fact_id=bounded.selected_fact_id,
        oracle_correct=oracle.correct,
        bounded_correct=bounded.correct,
        failure_mode=_classify_failure(oracle.correct, bounded.correct),
        eligible_bounded_fact_ids=eligible_bounded,
        eligible_oracle_fact_ids=eligible_oracle,
        history_recoverable=len(expanded.facts) == len(case.facts) + depth,
        dual_current_eligible_risk_bounded=_dual_current_eligible_risk(
            bounded_case, eligible_bounded
        ),
        reality_sources=list(case.reality_sources),
    )


def run_authority_replay(
    *,
    candidate_budget: int = DEFAULT_CANDIDATE_BUDGET,
    depths: tuple[int, ...] = SUPERSESSION_DEPTH_SWEEP,
    cases: list[MemoryReplayCase] | None = None,
    policy: VerifiedSupersessionPolicy | None = None,
) -> AuthorityReplayReport:
    policy = policy or VerifiedSupersessionPolicy()
    cases = cases or issue_derived_memory_cases()
    observations: list[AuthorityReplayObservation] = []
    for case in cases:
        for depth in depths:
            observations.append(
                observe_case(
                    case,
                    depth=depth,
                    candidate_budget=candidate_budget,
                    policy=policy,
                )
            )
    return AuthorityReplayReport(
        candidate_budget=candidate_budget,
        depth_sweep=list(depths),
        policy=policy.name,
        observations=observations,
    )
