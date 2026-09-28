from pathlib import Path
import importlib.util
import json


MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "render_gate5_drift_diff.py"
spec = importlib.util.spec_from_file_location("gate5_diff", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def _proof(run_id: str, recall: float, cost: float, latency: float, scale20: float, gate5=None):
    return {
        "run_id": run_id,
        "snapshot": {
            "run_id": run_id,
            "evidence_recall": recall,
            "task_accuracy": 0.92,
            "authority_accuracy": 0.97,
            "negative_accuracy": 0.99,
            "estimated_cost_usd": cost,
            "latency_seconds": latency,
        },
        "gate4": {
            "status": "pass",
            "points": [{
                "requested_ratio": 20,
                "evidence_recall": scale20,
                "baseline_evidence_recall": {
                    "lexical-top-5": 0.30,
                    "lexical-top-20": 0.50,
                },
            }],
        },
        "gate5": gate5,
    }


def test_gate5_diff_surfaces_quality_operations_and_20x_change():
    reference = _proof("r1", 0.95, 2.0, 40.0, 0.94)
    candidate = _proof(
        "r2", 0.90, 3.0, 60.0, 0.88,
        gate5={
            "status": "fail",
            "blockers": ["r2:evidence-recall-drop=0.050"],
            "deltas": [{"config_fingerprint": "abc123"}],
        },
    )

    diff = mod.build_diff(reference, candidate)

    assert diff["status"] == "fail"
    assert round(diff["quality"]["evidence_recall"]["delta"], 4) == -0.05
    assert diff["operations"]["estimated_cost_usd"]["ratio"] == 1.5
    assert diff["operations"]["latency_seconds"]["ratio"] == 1.5
    assert round(diff["scale_20x"]["contextmesh_evidence_recall"]["delta"], 4) == -0.06
    md = mod.render_markdown(diff)
    assert "20× Scale Point" in md
    assert "ContextMesh recall" in md
    assert "Blockers" in md


def test_gate5_diff_reports_not_comparable_without_reference():
    diff = mod.build_diff(None, _proof("r2", 0.9, 1.0, 10.0, 0.8))
    assert diff["status"] == "not-comparable"
    assert "NOT COMPARABLE" in mod.render_markdown(diff)
