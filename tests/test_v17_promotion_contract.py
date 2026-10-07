from pathlib import Path
import importlib.util


MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "decide_big_context_promotion.py"
spec = importlib.util.spec_from_file_location("promotion", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def _diff(status="pass", scale_delta=0.0, cost_ratio=1.0, latency_ratio=1.0, blockers=None):
    return {
        "status": status,
        "reference_run_id": "r1",
        "candidate_run_id": "r2",
        "scale_20x": {
            "contextmesh_evidence_recall": {"delta": scale_delta}
        },
        "operations": {
            "estimated_cost_usd": {"ratio": cost_ratio},
            "latency_seconds": {"ratio": latency_ratio},
        },
        "blockers": blockers or [],
    }


def test_promotion_promotes_clean_candidate():
    result = mod.decide(_diff())
    assert result["decision"] == "PROMOTE"
    assert result["hard_failures"] == []


def test_promotion_rejects_quality_scale_and_operational_regressions():
    result = mod.decide(
        _diff(
            status="fail",
            scale_delta=-0.08,
            cost_ratio=1.5,
            latency_ratio=1.4,
            blockers=["r2:evidence-recall-drop=0.060"],
        )
    )
    assert result["decision"] == "REJECT"
    text = " ".join(result["hard_failures"])
    assert "gate5-status=fail" in text
    assert "scale20-contextmesh-recall-drop" in text
    assert "cost-ratio=" in text
    assert "latency-ratio=" in text


def test_promotion_holds_when_comparison_is_missing():
    result = mod.decide({"status": "not-comparable"})
    assert result["decision"] == "HOLD"


def test_promotion_holds_when_operations_are_unavailable_but_quality_passes():
    diff = _diff()
    diff["operations"]["estimated_cost_usd"]["ratio"] = None
    diff["operations"]["latency_seconds"]["ratio"] = None
    result = mod.decide(diff)
    assert result["decision"] == "HOLD"
    assert "cost-ratio-unavailable" in result["warnings"]


def test_promotion_rejects_relaxed_policy_before_decision():
    for kwargs in [
        {"max_cost_ratio": 999},
        {"max_latency_ratio": 999},
        {"max_scale20_recall_drop": 1.0},
    ]:
        try:
            mod.decide(_diff(), **kwargs)
        except ValueError as exc:
            assert "exceeds approved" in str(exc)
        else:
            raise AssertionError("expected relaxed promotion policy rejection")


def test_promotion_rejects_negative_policy_thresholds():
    try:
        mod.decide(_diff(), max_scale20_recall_drop=-0.01)
    except ValueError as exc:
        assert "must be non-negative" in str(exc)
    else:
        raise AssertionError("expected negative threshold rejection")


def test_promotion_rejects_non_finite_policy_thresholds():
    for value in [float("nan"), float("inf"), float("-inf")]:
        try:
            mod.decide(_diff(), max_cost_ratio=value)
        except ValueError as exc:
            assert "must be finite" in str(exc)
        else:
            raise AssertionError("expected non-finite threshold rejection")


def test_promotion_rejects_non_finite_artifact_metrics_without_crashing():
    for value in [float("nan"), float("inf"), float("-inf")]:
        diff = _diff()
        diff["operations"]["estimated_cost_usd"]["ratio"] = value
        result = mod.decide(diff)
        assert result["decision"] == "REJECT"
        assert any("invalid-metric:" in item for item in result["hard_failures"])


def test_promotion_rejects_malformed_artifact_metric_without_crashing():
    diff = _diff()
    diff["scale_20x"]["contextmesh_evidence_recall"]["delta"] = "garbage"
    result = mod.decide(diff)
    assert result["decision"] == "REJECT"
    assert any("must be numeric" in item for item in result["hard_failures"])


def test_promotion_rejects_invalid_or_colliding_run_identities():
    for reference, candidate in [(" ", "r2"), (1, "r2"), (" r1", "r2"), ("r1", "r1")]:
        diff = _diff()
        diff["reference_run_id"] = reference
        diff["candidate_run_id"] = candidate
        result = mod.decide(diff)
        assert result["decision"] == "REJECT"


def test_promotion_rejects_invalid_gate5_status_type_or_value():
    for status in [True, 1, "PASS", "unknown", ""]:
        result = mod.decide(_diff(status=status))
        assert result["decision"] == "REJECT"
        assert "invalid-gate5-status" in result["hard_failures"]


def test_promotion_rejects_malformed_blockers_contract():
    for blockers in ["oops", {"x": 1}, [""], [1], [True]]:
        diff = _diff()
        diff["blockers"] = blockers
        result = mod.decide(diff)
        assert result["decision"] == "REJECT"
        assert "invalid-gate5-blockers" in result["hard_failures"]
