from contextmesh.evidence_consumer import evidence_check


def test_missing_summary_holds() -> None:
    assert evidence_check(None)["decision"] == "hold"
    assert evidence_check(None)["reasons"] == ["evidence-summary-missing"]


def test_passed_gate3_gate4_without_gate5_can_continue() -> None:
    summary = {
        "schema_version": 1,
        "gates": {
            "gate3": {"status": "pass"},
            "gate4": {"status": "pass", "blockers": []},
            "gate5": {"status": "not-run"},
        },
        "gate5_failure_onset": {"earlier": 0},
    }
    result = evidence_check(summary)
    assert result["decision"] == "pass"
    assert result["reasons"] == []
    assert result["policy"] == "evidence-readiness-only-not-promotion"


def test_failed_gate_and_blocker_hold_with_reasons() -> None:
    summary = {
        "schema_version": 1,
        "gates": {
            "gate3": {"status": "pass"},
            "gate4": {"status": "fail", "blockers": ["scale-point-failed:20x"]},
            "gate5": {"status": "not-run"},
        },
        "gate5_failure_onset": {"earlier": 0},
    }
    result = evidence_check(summary)
    assert result["decision"] == "hold"
    assert "gate4:fail" in result["reasons"]
    assert "gate4-blocker:scale-point-failed:20x" in result["reasons"]


def test_failure_onset_regression_is_diagnostic_hold() -> None:
    summary = {
        "schema_version": 1,
        "gates": {
            "gate3": {"status": "pass"},
            "gate4": {"status": "pass", "blockers": []},
            "gate5": {"status": "pass"},
        },
        "gate5_failure_onset": {"earlier": 2},
    }
    result = evidence_check(summary)
    assert result["decision"] == "hold"
    assert result["reasons"] == ["failure-onset-earlier:2"]


def test_unsupported_schema_version_holds() -> None:
    summary = {
        "schema_version": 2,
        "gates": {
            "gate3": {"status": "pass"},
            "gate4": {"status": "pass", "blockers": []},
            "gate5": {"status": "not-run"},
        },
        "gate5_failure_onset": {"earlier": 0},
    }
    result = evidence_check(summary)
    assert result["decision"] == "hold"
    assert "unsupported-schema-version:2" in result["reasons"]


def test_malformed_failure_onset_count_holds_without_crashing() -> None:
    summary = {
        "schema_version": 1,
        "gates": {
            "gate3": {"status": "pass"},
            "gate4": {"status": "pass", "blockers": []},
            "gate5": {"status": "not-run"},
        },
        "gate5_failure_onset": {"earlier": "not-a-number"},
    }
    result = evidence_check(summary)
    assert result["decision"] == "hold"
    assert "invalid-failure-onset-count" in result["reasons"]


def test_malformed_gates_hold_without_crashing() -> None:
    result = evidence_check({
        "schema_version": 1,
        "gates": ["gate3", "gate4"],
        "gate5_failure_onset": {"earlier": 0},
    })
    assert result["decision"] == "hold"
    assert "invalid-gates" in result["reasons"]
    assert "gate3:invalid" in result["reasons"]
    assert "gate4:invalid" in result["reasons"]


def test_malformed_blockers_hold_without_iterating_string() -> None:
    summary = {
        "schema_version": 1,
        "gates": {
            "gate3": {"status": "pass"},
            "gate4": {"status": "pass", "blockers": "bad-shape"},
            "gate5": {"status": "not-run"},
        },
        "gate5_failure_onset": {"earlier": 0},
    }
    result = evidence_check(summary)
    assert result["decision"] == "hold"
    assert "gate4-blockers:invalid" in result["reasons"]


def test_boolean_failure_onset_count_is_rejected() -> None:
    summary = {
        "schema_version": 1,
        "gates": {
            "gate3": {"status": "pass"},
            "gate4": {"status": "pass", "blockers": []},
            "gate5": {"status": "not-run"},
        },
        "gate5_failure_onset": {"earlier": True},
    }
    result = evidence_check(summary)
    assert result["decision"] == "hold"
    assert result["reasons"] == ["invalid-failure-onset-count"]


def test_numeric_string_failure_onset_count_is_rejected() -> None:
    summary = {
        "schema_version": 1,
        "gates": {
            "gate3": {"status": "pass"},
            "gate4": {"status": "pass", "blockers": []},
            "gate5": {"status": "not-run"},
        },
        "gate5_failure_onset": {"earlier": "2"},
    }
    result = evidence_check(summary)
    assert result["decision"] == "hold"
    assert result["reasons"] == ["invalid-failure-onset-count"]
