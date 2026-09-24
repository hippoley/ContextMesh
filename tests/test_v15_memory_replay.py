from contextmesh.memory_replay import (
    DestructiveNewestWinsPolicy,
    LastWriteWinsPolicy,
    VerifiedSupersessionPolicy,
    issue_derived_memory_cases,
    run_memory_replay,
)


def _cases():
    return {x.id: x for x in issue_derived_memory_cases()}


def test_newer_transient_fact_breaks_last_write_wins():
    case = _cases()["transient-newer-is-not-truth"]
    naive = LastWriteWinsPolicy().decide(case)
    verified = VerifiedSupersessionPolicy().decide(case)
    assert naive.selected_fact_id == "db-port-transient"
    assert naive.correct is False
    assert verified.selected_fact_id == "db-port-stable"
    assert verified.correct is True


def test_expired_override_requires_validity_interval_not_recency():
    case = _cases()["temporary-override-expired"]
    naive = LastWriteWinsPolicy().decide(case)
    verified = VerifiedSupersessionPolicy().decide(case)
    assert naive.selected_fact_id == "region-emergency"
    assert naive.correct is False
    assert verified.selected_fact_id == "region-primary"
    assert verified.correct is True


def test_real_verified_change_still_wins():
    case = _cases()["verified-preference-change"]
    verified = VerifiedSupersessionPolicy().decide(case)
    assert verified.selected_fact_id == "theme-light"
    assert verified.correct is True


def test_refuted_latest_write_does_not_shadow_truth_under_soft_lifecycle():
    case = _cases()["refuted-latest-write"]
    verified = VerifiedSupersessionPolicy().decide(case)
    assert verified.selected_fact_id == "status-green"
    assert verified.correct is True


def test_destructive_policy_loses_audit_history():
    report = run_memory_replay()
    destructive = [x for x in report.decisions if x.policy == "destructive-newest-wins"]
    assert destructive
    assert all(x.audit_preserved is False for x in destructive)


def test_verified_policy_solves_all_issue_derived_cases():
    report = run_memory_replay()
    stats = report.by_policy["verified-supersession"]
    assert stats["cases"] == 4
    assert stats["correct"] == 4
    assert stats["accuracy"] == 1.0
