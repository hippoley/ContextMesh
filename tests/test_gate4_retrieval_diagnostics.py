from __future__ import annotations

from contextmesh.gate4_diagnostics import failure_classification


def test_failure_classification_distinguishes_baseline_and_scale_regression() -> None:
    points = [
        {
            "requested_ratio": 1.0,
            "cases": [
                {"case_id": "stable", "expected_present": True, "recovered": True},
                {"case_id": "regress", "expected_present": True, "recovered": True},
                {"case_id": "baseline", "expected_present": True, "recovered": False},
            ],
        },
        {
            "requested_ratio": 5.0,
            "cases": [
                {"case_id": "stable", "expected_present": True, "recovered": True},
                {"case_id": "regress", "expected_present": True, "recovered": False},
                {"case_id": "baseline", "expected_present": True, "recovered": False},
            ],
        },
    ]

    assert failure_classification(points, "stable", "cases") == {
        "classification": "stable",
        "first_failure_scale": None,
    }
    assert failure_classification(points, "regress", "cases") == {
        "classification": "scale-regression",
        "first_failure_scale": 5.0,
    }
    assert failure_classification(points, "baseline", "cases") == {
        "classification": "baseline-incapable",
        "first_failure_scale": 1.0,
    }


def test_failure_classification_handles_no_positive_case() -> None:
    points = [{
        "requested_ratio": 1.0,
        "cases": [{"case_id": "negative", "expected_present": False, "recovered": None}],
    }]
    assert failure_classification(points, "negative", "cases") == {
        "classification": "not-applicable",
        "first_failure_scale": None,
    }
