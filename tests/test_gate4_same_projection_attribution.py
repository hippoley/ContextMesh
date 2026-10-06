from __future__ import annotations

from contextmesh.gate4_reporting import render_markdown


def test_render_same_projection_attribution() -> None:
    proof = {
        "gate4": {
            "status": "pass",
            "points": [{
                "requested_ratio": 20,
                "actual_ratio": 20.0,
                "status": "pass",
                "selected_blocks": 1318,
                "baseline_evidence_recall": {},
                "case_attribution": {
                    "lexical-top-20": [{
                        "case_id": "cross-file-008",
                        "lexical_recovered": False,
                        "contextmesh_recovered": True,
                        "classification": "contextmesh-recovery-win",
                    }]
                },
            }],
        }
    }
    text = render_markdown(proof, [])
    assert "## Same-projection attribution" in text
    assert "cross-file-008" in text
    assert "contextmesh-recovery-win" in text


def test_attribution_is_observational_for_status() -> None:
    proof = {
        "gate4": {
            "status": "fail",
            "points": [{
                "requested_ratio": 20,
                "status": "fail",
                "baseline_evidence_recall": {},
                "case_attribution": {
                    "lexical-top-20": [{
                        "case_id": "case",
                        "lexical_recovered": False,
                        "contextmesh_recovered": True,
                        "classification": "contextmesh-recovery-win",
                    }]
                },
            }],
            "blockers": ["scale-point-failed:20x"],
        }
    }
    text = render_markdown(proof, [])
    assert "Status: **FAIL**" in text
    assert "scale-point-failed:20x" in text
