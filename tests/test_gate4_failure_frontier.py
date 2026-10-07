from __future__ import annotations

from contextmesh.gate4_diagnostics import failure_frontier, failure_mechanism


def _diag(
    *,
    recovered: bool,
    first_hit: int | None,
    sufficient: int | None,
    reason: str = "asset-miss",
) -> dict[str, object]:
    return {
        "case_id": "cross-file-008",
        "expected_present": True,
        "recovered": recovered,
        "best_ground_truth_rank": first_hit,
        "first_sufficient_rank": sufficient,
        "failure_reason": reason,
    }


def test_failure_mechanism_distinguishes_first_hit_from_sufficient_rank() -> None:
    result = failure_mechanism(
        _diag(
            recovered=False,
            first_hit=4,
            sufficient=27,
        ),
        top_k=20,
    )

    assert result["mechanism"] == "partial-evidence-below-sufficiency"
    assert result["recovery_top_k"] == 27
    assert result["rank_gap"] == 7


def test_failure_frontier_reports_observed_breakpoint_bracket() -> None:
    points = [
        {
            "requested_ratio": 1,
            "lexical_top_20_cases": [
                _diag(recovered=True, first_hit=2, sufficient=8),
            ],
        },
        {
            "requested_ratio": 2,
            "lexical_top_20_cases": [
                _diag(recovered=False, first_hit=3, sufficient=24),
            ],
        },
        {
            "requested_ratio": 5,
            "lexical_top_20_cases": [
                _diag(recovered=False, first_hit=7, sufficient=33),
            ],
        },
    ]

    frontier = failure_frontier(
        points,
        "cross-file-008",
        "lexical_top_20_cases",
        top_k=20,
    )

    assert frontier["classification"] == "scale-regression"
    assert frontier["last_recovered_scale"] == 1
    assert frontier["first_failure_scale"] == 2
    assert frontier["breakpoint_bracket"] == {
        "greater_than": 1,
        "less_than_or_equal": 2,
    }
    assert frontier["mechanism"] == "partial-evidence-below-sufficiency"
    assert frontier["recovery_top_k"] == 24
    assert frontier["rank_gap"] == 4


def test_failure_frontier_does_not_invent_unmeasured_breakpoint() -> None:
    points = [
        {
            "requested_ratio": 1,
            "lexical_top_5_cases": [
                _diag(recovered=True, first_hit=1, sufficient=4),
            ],
        },
        {
            "requested_ratio": 5,
            "lexical_top_5_cases": [
                _diag(recovered=False, first_hit=6, sufficient=9),
            ],
        },
    ]

    frontier = failure_frontier(
        points,
        "cross-file-008",
        "lexical_top_5_cases",
        top_k=5,
    )

    assert frontier["first_failure_scale"] == 5
    assert frontier["breakpoint_bracket"] == {
        "greater_than": 1,
        "less_than_or_equal": 5,
    }
    assert "exact_breakpoint" not in frontier


def test_baseline_failure_is_not_called_scale_regression() -> None:
    points = [
        {
            "requested_ratio": 1,
            "lexical_top_5_cases": [
                _diag(recovered=False, first_hit=9, sufficient=12),
            ],
        },
    ]

    frontier = failure_frontier(
        points,
        "cross-file-008",
        "lexical_top_5_cases",
        top_k=5,
    )

    assert frontier["classification"] == "baseline-incapable"
    assert frontier["last_recovered_scale"] is None
    assert frontier["first_failure_scale"] == 1
    assert frontier["breakpoint_bracket"] is None
    assert frontier["mechanism"] == "first-hit-beyond-budget"
