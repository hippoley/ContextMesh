from contextmesh.evidence_reporting import build_evidence_report


def test_evidence_report_keeps_missing_live_proof_not_run() -> None:
    text = build_evidence_report(None)
    assert "LIVE PROOF NOT RUN" in text


def test_evidence_report_summarizes_existing_evidence_without_rejudging() -> None:
    proof = {
        "gate3": {"status": "pass"},
        "gate4": {
            "status": "fail",
            "points": [{
                "requested_ratio": 20,
                "evidence_recall": 0.91,
                "baseline_evidence_recall": {"lexical-top-20": 0.18},
                "case_attribution": {"lexical-top-20": [
                    {"classification": "contextmesh-recovery-win"},
                    {"classification": "contextmesh-regression"},
                ]},
            }],
            "blockers": ["scale-point-failed:20x"],
        },
    }
    drift = {
        "status": "fail",
        "scale_case_drift": {"failure_onset": [
            {"case_id": "cross-file-008", "reference_first_failure_ratio": 10, "candidate_first_failure_ratio": 5, "classification": "failure-onset-earlier"},
            {"case_id": "semantic-003", "reference_first_failure_ratio": 5, "candidate_first_failure_ratio": 10, "classification": "failure-onset-later"},
        ]},
    }
    text = build_evidence_report(proof, drift)
    assert "| Gate 4 | FAIL |" in text
    assert "| 20 | 0.91 | 0.18 | 1 | 1 |" in text
    assert "Failure onset earlier: **1**" in text
    assert "cross-file-008: 10x -> 5x" in text
    assert "scale-point-failed:20x" in text
    assert "diagnostic classifications do not override" in text
