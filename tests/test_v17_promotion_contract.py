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
