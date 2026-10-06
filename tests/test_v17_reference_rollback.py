from pathlib import Path
import importlib.util
import json


LINEAGE_PATH = Path(__file__).parents[1] / "benchmarks" / "update_promotion_lineage.py"
spec1 = importlib.util.spec_from_file_location("lineage", LINEAGE_PATH)
lineage = importlib.util.module_from_spec(spec1)
assert spec1 and spec1.loader
spec1.loader.exec_module(lineage)

ROLLBACK_PATH = Path(__file__).parents[1] / "benchmarks" / "rollback_promotion_lineage.py"
spec2 = importlib.util.spec_from_file_location("rollback", ROLLBACK_PATH)
rollback_mod = importlib.util.module_from_spec(spec2)
assert spec2 and spec2.loader
spec2.loader.exec_module(rollback_mod)


def _decision(reference, candidate, outcome="PROMOTE"):
    return {
        "schema_version": 1,
        "decision": outcome,
        "reference_run_id": reference,
        "candidate_run_id": candidate,
        "hard_failures": [],
        "warnings": [],
        "policy": {
            "max_cost_ratio": 1.25,
            "max_latency_ratio": 1.25,
            "max_scale20_recall_drop": 0.05,
            "requires_gate5_pass": True,
            "requires_scale20_comparability": True,
        },
    }


def _chain():
    first = lineage.build_lineage(_decision("A", "B"))
    return lineage.build_lineage(_decision("B", "C"), prior_lineage=first)


def test_rollback_moves_reference_to_promoted_ancestor_and_preserves_history():
    prior = _chain()
    result = rollback_mod.rollback(
        prior,
        target_run_id="B",
        reason="production-adjacent incident exposed an unmodelled failure",
        incident_ref="INC-42",
        operator="release-bot",
    )
    assert result["current_reference_run_id"] == "B"
    assert result["rollback_count"] == 1
    assert result["event_count"] == prior["event_count"] + 1
    event = result["events"][-1]
    assert event["event_type"] == "ROLLBACK"
    assert event["from_reference_run_id"] == "C"
    assert event["to_reference_run_id"] == "B"
    assert result["supersedes_lineage_fingerprint"] == prior["lineage_fingerprint"]
    assert result["lineage_fingerprint"] != prior["lineage_fingerprint"]


def test_rollback_can_return_to_root_reference():
    prior = _chain()
    result = rollback_mod.rollback(prior, target_run_id="A", reason="recover root")
    assert result["current_reference_run_id"] == "A"


def test_rollback_rejects_never_promoted_candidate():
    prior = _chain()
    rejected = lineage.build_lineage(_decision("C", "D", "REJECT"), prior_lineage=prior)
    try:
        rollback_mod.rollback(rejected, target_run_id="D", reason="invalid")
    except ValueError as exc:
        assert "not a previously promoted reference" in str(exc)
    else:
        raise AssertionError("expected rollback target rejection")


def test_rollback_rejects_current_reference_and_missing_reason():
    prior = _chain()
    for target, reason, marker in [
        ("C", "same", "already the current reference"),
        ("B", "   ", "reason is required"),
    ]:
        try:
            rollback_mod.rollback(prior, target_run_id=target, reason=reason)
        except ValueError as exc:
            assert marker in str(exc)
        else:
            raise AssertionError("expected rollback validation error")


def test_rollback_rejects_tampered_lineage():
    prior = _chain()
    prior["events"][0]["decision"] = "REJECT"
    try:
        rollback_mod.rollback(prior, target_run_id="A", reason="tampered")
    except ValueError as exc:
        assert "fingerprint mismatch" in str(exc)
    else:
        raise AssertionError("expected fingerprint failure")
