from contextmesh.gate5_reporting import case_drift_rows


def _point(rows):
    return {"case_results": rows}


def test_case_drift_classifies_recovery_transitions() -> None:
    reference = _point([
        {"case_id": "lost", "kind": "exact", "expected_present": True, "recovered": True, "term_recall": 1.0, "coverage": 1.0},
        {"case_id": "gain", "kind": "exact", "expected_present": True, "recovered": False, "term_recall": 0.0, "coverage": 1.0},
        {"case_id": "stable", "kind": "exact", "expected_present": True, "recovered": True, "term_recall": 1.0, "coverage": 1.0},
    ])
    candidate = _point([
        {"case_id": "lost", "kind": "exact", "expected_present": True, "recovered": False, "term_recall": 0.0, "coverage": 1.0},
        {"case_id": "gain", "kind": "exact", "expected_present": True, "recovered": True, "term_recall": 1.0, "coverage": 1.0},
        {"case_id": "stable", "kind": "exact", "expected_present": True, "recovered": True, "term_recall": 1.0, "coverage": 1.0},
    ])
    classes = {row["case_id"]: row["classification"] for row in case_drift_rows(reference, candidate)}
    assert classes == {
        "gain": "lost-to-recovered",
        "lost": "recovered-to-lost",
        "stable": "stable-recovered",
    }


def test_case_drift_marks_missing_case_not_comparable() -> None:
    rows = case_drift_rows(
        _point([{"case_id": "only-ref", "recovered": True}]),
        _point([]),
    )
    assert rows[0]["classification"] == "not-comparable"
