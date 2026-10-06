from contextmesh.gate5_reporting import scale_case_drift_matrix


def _proof(states):
    return {
        "gate4": {
            "points": [
                {
                    "requested_ratio": ratio,
                    "case_results": [
                        {"case_id": case_id, "expected_present": True, "recovered": recovered}
                        for case_id, recovered in cases.items()
                    ],
                }
                for ratio, cases in states
            ]
        }
    }


def test_failure_onset_detects_earlier_and_later_boundaries() -> None:
    reference = _proof([
        (1, {"earlier": True, "later": True, "never": True}),
        (2, {"earlier": True, "later": False, "never": True}),
        (5, {"earlier": True, "later": False, "never": True}),
        (10, {"earlier": False, "later": False, "never": True}),
        (20, {"earlier": False, "later": False, "never": True}),
    ])
    candidate = _proof([
        (1, {"earlier": True, "later": True, "never": True}),
        (2, {"earlier": True, "later": True, "never": True}),
        (5, {"earlier": False, "later": True, "never": True}),
        (10, {"earlier": False, "later": False, "never": True}),
        (20, {"earlier": False, "later": False, "never": True}),
    ])
    rows = {r["case_id"]: r for r in scale_case_drift_matrix(reference, candidate)["failure_onset"]}
    assert rows["earlier"]["classification"] == "failure-onset-earlier"
    assert rows["earlier"]["reference_first_failure_ratio"] == 10.0
    assert rows["earlier"]["candidate_first_failure_ratio"] == 5.0
    assert rows["later"]["classification"] == "failure-onset-later"
    assert rows["later"]["reference_first_failure_ratio"] == 2.0
    assert rows["later"]["candidate_first_failure_ratio"] == 10.0
    assert rows["never"]["classification"] == "failure-onset-stable"
    assert rows["never"]["reference_first_failure_ratio"] is None
    assert rows["never"]["candidate_first_failure_ratio"] is None


def test_failure_onset_requires_case_at_every_scale() -> None:
    reference = _proof([(1, {"case": True}), (2, {"case": False})])
    candidate = _proof([(1, {"case": True}), (2, {})])
    row = scale_case_drift_matrix(reference, candidate)["failure_onset"][0]
    assert row["classification"] == "not-comparable"
