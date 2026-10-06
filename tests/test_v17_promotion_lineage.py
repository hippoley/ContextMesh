from pathlib import Path
import importlib.util


MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "update_promotion_lineage.py"
spec = importlib.util.spec_from_file_location("lineage", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def _decision(reference, candidate, outcome):
    return {
        "schema_version": 1,
        "decision": outcome,
        "reference_run_id": reference,
        "candidate_run_id": candidate,
        "hard_failures": [] if outcome != "REJECT" else ["quality-regression"],
        "warnings": [] if outcome != "HOLD" else ["cost-ratio-unavailable"],
        "policy": {
            "max_cost_ratio": 1.25,
            "max_latency_ratio": 1.25,
            "max_scale20_recall_drop": 0.05,
            "requires_gate5_pass": True,
            "requires_scale20_comparability": True,
        },
    }


def test_promote_moves_current_reference_and_preserves_chain():
    first = mod.build_lineage(
        _decision("A", "B", "PROMOTE"),
        expected_reference_run_id="A",
        expected_candidate_run_id="B",
        candidate_git_sha="sha-b",
    )
    assert first["root_reference_run_id"] == "A"
    assert first["current_reference_run_id"] == "B"
    assert first["event_count"] == 1

    second = mod.build_lineage(
        _decision("B", "C", "REJECT"),
        prior_lineage=first,
        expected_reference_run_id="B",
        expected_candidate_run_id="C",
        candidate_git_sha="sha-c",
    )
    assert second["current_reference_run_id"] == "B"
    assert [x["decision"] for x in second["events"]] == ["PROMOTE", "REJECT"]

    third = mod.build_lineage(
        _decision("B", "D", "PROMOTE"),
        prior_lineage=second,
        expected_reference_run_id="B",
        expected_candidate_run_id="D",
    )
    assert third["current_reference_run_id"] == "D"
    assert third["event_count"] == 3
    assert third["lineage_fingerprint"] != second["lineage_fingerprint"]


def test_hold_does_not_move_reference():
    lineage = mod.build_lineage(_decision("A", "B", "HOLD"))
    assert lineage["current_reference_run_id"] == "A"


def test_lineage_rejects_reference_fork():
    prior = mod.build_lineage(_decision("A", "B", "PROMOTE"))
    try:
        mod.build_lineage(_decision("A", "C", "PROMOTE"), prior_lineage=prior)
    except ValueError as exc:
        assert "lineage fork rejected" in str(exc)
    else:
        raise AssertionError("expected lineage fork rejection")


def test_lineage_rejects_tampered_prior_fingerprint():
    prior = mod.build_lineage(_decision("A", "B", "PROMOTE"))
    prior["events"][0]["decision"] = "REJECT"
    try:
        mod.build_lineage(_decision("B", "C", "PROMOTE"), prior_lineage=prior)
    except ValueError as exc:
        assert "fingerprint mismatch" in str(exc)
    else:
        raise AssertionError("expected fingerprint mismatch")


def test_lineage_rejects_workflow_identity_mismatch():
    try:
        mod.build_lineage(
            _decision("A", "B", "PROMOTE"),
            expected_reference_run_id="WRONG",
            expected_candidate_run_id="B",
        )
    except ValueError as exc:
        assert "reference run mismatch" in str(exc)
    else:
        raise AssertionError("expected identity mismatch")


def test_append_after_rollback_preserves_rollback_history_and_count():
    first = mod.build_lineage(_decision("A", "B", "PROMOTE"))
    first["schema_version"] = 2
    first["rollback_count"] = 1
    first["supersedes_lineage_fingerprint"] = first["lineage_fingerprint"]
    # Re-fingerprint after simulating a valid rollback-derived lineage envelope.
    first["lineage_fingerprint"] = mod._fingerprint(first)

    second = mod.build_lineage(
        _decision("B", "C", "PROMOTE"),
        prior_lineage=first,
        expected_reference_run_id="B",
        expected_candidate_run_id="C",
    )
    assert second["schema_version"] == 2
    assert second["rollback_count"] == 1
    assert second["supersedes_lineage_fingerprint"] == first["supersedes_lineage_fingerprint"]


def test_lineage_rejects_unversioned_promotion_artifact():
    decision = _decision("A", "B", "PROMOTE")
    decision.pop("schema_version")
    try:
        mod.build_lineage(decision)
    except ValueError as exc:
        assert "unsupported promotion decision schema" in str(exc)
    else:
        raise AssertionError("expected schema rejection")


def test_lineage_rejects_weakened_promotion_policy():
    decision = _decision("A", "B", "PROMOTE")
    decision["policy"]["requires_gate5_pass"] = False
    try:
        mod.build_lineage(decision)
    except ValueError as exc:
        assert "must require Gate 5 PASS" in str(exc)
    else:
        raise AssertionError("expected weakened policy rejection")
