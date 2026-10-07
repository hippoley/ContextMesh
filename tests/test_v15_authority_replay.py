from contextmesh.authority_replay import (
    DEFAULT_CANDIDATE_BUDGET,
    run_authority_replay,
)
from contextmesh.memory_replay import issue_derived_memory_cases


def test_authority_replay_depth_zero_stays_correct_under_budget():
    report = run_authority_replay(depths=(0,))
    rows = [x for x in report.observations if x.superseded_history_depth == 0]
    assert len(rows) == len(issue_derived_memory_cases())
    assert all(x.oracle_correct for x in rows)
    assert all(x.bounded_correct for x in rows)
    assert all(x.failure_mode == "none" for x in rows)


def test_depth_pressure_surfaces_candidate_visibility_not_policy_error():
    report = run_authority_replay(depths=(20,))
    pressured = [
        x
        for x in report.observations
        if x.scenario_id == "transient-newer-is-not-truth"
        and x.superseded_history_depth == 20
    ]
    assert len(pressured) == 1
    row = pressured[0]
    assert row.oracle_correct
    assert not row.bounded_correct
    assert row.failure_mode == "candidate-visibility"
    assert not row.authoritative_survives_budget
    assert row.authoritative_candidate_rank > DEFAULT_CANDIDATE_BUDGET


def test_first_candidate_visibility_failure_depth_is_reported():
    report = run_authority_replay()
    first = report.first_candidate_visibility_failure_by_scenario
    assert first["transient-newer-is-not-truth"] == 10
    assert first["temporary-override-expired"] == 10
    assert first["refuted-latest-write"] == 10
    assert first["verified-preference-change"] == 10


def test_report_markdown_and_json_shapes():
    report = run_authority_replay(depths=(0, 5))
    md = report.to_markdown()
    assert "Authority replay under supersession depth" in md
    assert "50+" not in md or "verified-preference-change" in md
    payload = report.model_dump()
    assert payload["kind"] == "contextmesh-authority-replay-probe"
    assert payload["candidate_budget"] == DEFAULT_CANDIDATE_BUDGET
