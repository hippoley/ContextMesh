from pathlib import Path
import importlib.util


LINEAGE_PATH = Path(__file__).parents[1] / "benchmarks" / "update_promotion_lineage.py"
s1 = importlib.util.spec_from_file_location("lineage", LINEAGE_PATH)
lineage = importlib.util.module_from_spec(s1)
assert s1 and s1.loader
s1.loader.exec_module(lineage)

ROLLBACK_PATH = Path(__file__).parents[1] / "benchmarks" / "rollback_promotion_lineage.py"
s2 = importlib.util.spec_from_file_location("rollback", ROLLBACK_PATH)
rollback = importlib.util.module_from_spec(s2)
assert s2 and s2.loader
s2.loader.exec_module(rollback)

RECOVERY_PATH = Path(__file__).parents[1] / "benchmarks" / "validate_recovery_context.py"
s3 = importlib.util.spec_from_file_location("recovery", RECOVERY_PATH)
recovery = importlib.util.module_from_spec(s3)
assert s3 and s3.loader
s3.loader.exec_module(recovery)


def _decision(reference, candidate):
    return {
        "schema_version": 1,
        "decision": "PROMOTE",
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


def test_post_rollback_candidate_requires_fresh_revalidation():
    a_b = lineage.build_lineage(_decision("A", "B"))
    b_c = lineage.build_lineage(_decision("B", "C"), prior_lineage=a_b)
    back_to_b = rollback.rollback(b_c, target_run_id="B", reason="incident")

    result = recovery.validate_recovery_context(
        back_to_b,
        reference_run_id="B",
        candidate_run_id="C-prime",
    )
    assert result["status"] == "revalidation-required"
    assert result["latest_rollback"]["from_reference_run_id"] == "C"
    assert result["latest_rollback"]["to_reference_run_id"] == "B"
    assert all(result["requirements"].values())


def test_recovery_context_rejects_stale_reference():
    a_b = lineage.build_lineage(_decision("A", "B"))
    try:
        recovery.validate_recovery_context(a_b, reference_run_id="A", candidate_run_id="C")
    except ValueError as exc:
        assert "recovery reference mismatch" in str(exc)
    else:
        raise AssertionError("expected stale reference rejection")
