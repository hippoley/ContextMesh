from benchmarks.render_gate4_scale_curve import case_rows, render_markdown


def test_case_rows_and_markdown_render_live_telemetry() -> None:
    proof = {
        "gate4": {
            "status": "pass",
            "max_completed_ratio": 20.0,
            "recall_drop": 0.0,
            "points": [{
                "requested_ratio": 20,
                "actual_ratio": 20.0,
                "status": "pass",
                "selected_blocks": 100,
                "baseline_evidence_recall": {},
                "case_results": [{
                    "case_id": "cross-file-008",
                    "kind": "cross-file",
                    "expected_present": True,
                    "recovered": True,
                    "term_recall": 1.0,
                    "coverage": 1.0,
                    "visited_blocks": 100,
                    "total_blocks": 100,
                    "judgment_valid": True,
                    "latency_seconds": 0.25,
                }],
            }],
        }
    }
    rows = case_rows(proof)
    assert rows[0]["case_id"] == "cross-file-008"
    rendered = render_markdown(proof, [])
    assert "## Live case telemetry" in rendered
    assert "cross-file-008" in rendered
    assert "100 / 100" in rendered
