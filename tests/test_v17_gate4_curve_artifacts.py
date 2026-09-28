from pathlib import Path
import importlib.util
import json


MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "render_gate4_scale_curve.py"
spec = importlib.util.spec_from_file_location("gate4_curve", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_curve_artifacts_preserve_contextmesh_and_lexical_counterfactual(tmp_path: Path):
    proof = {
        "gate4": {
            "status": "pass",
            "max_completed_ratio": 20.01,
            "recall_drop": 0.02,
            "blockers": [],
            "points": [
                {
                    "requested_ratio": 1,
                    "actual_ratio": 1.005,
                    "status": "pass",
                    "selected_blocks": 50,
                    "selected_assets": 8,
                    "estimated_tokens": 131700,
                    "evidence_recall": 0.96,
                    "baseline_evidence_recall": {
                        "lexical-top-5": 0.72,
                        "lexical-top-20": 0.88,
                    },
                    "evidence_term_fidelity": 0.95,
                    "negative_accuracy": 1.0,
                }
            ],
        }
    }
    src = tmp_path / "live-proof.json"
    src.write_text(json.dumps(proof), encoding="utf-8")
    csv_path = tmp_path / "curve.csv"
    md_path = tmp_path / "curve.md"

    mod.write_curve_artifacts(src, csv_path, md_path)

    csv_text = csv_path.read_text(encoding="utf-8")
    md_text = md_path.read_text(encoding="utf-8")
    assert "contextmesh_evidence_recall" in csv_text
    assert "lexical_top_5_evidence_recall" in csv_text
    assert "0.96" in csv_text
    assert "0.72" in csv_text
    assert "ContextMesh recall" in md_text
    assert "Lexical@20 recall" in md_text
    assert "20.0100" in md_text


def test_curve_markdown_says_not_run_when_gate4_absent(tmp_path: Path):
    src = tmp_path / "live-proof.json"
    src.write_text(json.dumps({"gate3": {"status": "pass"}}), encoding="utf-8")
    csv_path = tmp_path / "curve.csv"
    md_path = tmp_path / "curve.md"

    mod.write_curve_artifacts(src, csv_path, md_path)

    assert "NOT RUN" in md_path.read_text(encoding="utf-8")
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 1
