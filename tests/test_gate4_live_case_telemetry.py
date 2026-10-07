from __future__ import annotations

from contextmesh.big_context_proof import NeedleKind, NeedleRunResult
from contextmesh.gate4_diagnostics import (
    compare_live_to_lexical,
    live_attribution_frontier,
    live_attribution_frontiers,
)


def _live(case_id: str, recovered: bool) -> NeedleRunResult:
    return NeedleRunResult(
        case_id=case_id,
        kind=NeedleKind.EXACT,
        expected_present=True,
        recovered=recovered,
        term_recall=1.0 if recovered else 0.0,
        coverage=1.0,
        judgment_valid=True,
    )


def test_compare_live_to_lexical_four_quadrants() -> None:
    lexical = [
        {"case_id": "win", "recovered": False},
        {"case_id": "regress", "recovered": True},
        {"case_id": "shared", "recovered": False},
        {"case_id": "stable", "recovered": True},
    ]
    rows = compare_live_to_lexical(
        lexical,
        [_live("win", True), _live("regress", False), _live("shared", False), _live("stable", True)],
    )
    assert {row["case_id"]: row["classification"] for row in rows} == {
        "win": "contextmesh-recovery-win",
        "regress": "contextmesh-regression",
        "shared": "shared-evidence-bottleneck",
        "stable": "stable",
    }


def test_compare_live_to_lexical_does_not_mutate_scored_result() -> None:
    live = _live("case", True)
    before = live.model_dump()
    compare_live_to_lexical([{"case_id": "case", "recovered": False}], [live])
    assert live.model_dump() == before



def _point(
    scale: float,
    *,
    classification: str,
    lexical_recovered: bool,
    contextmesh_recovered: bool,
    baseline: str = "lexical-top-20",
) -> dict[str, object]:
    return {
        "requested_ratio": scale,
        "status": "pass",
        "case_attribution": {
            baseline: [
                {
                    "case_id": "cross-file-008",
                    "kind": "cross-file",
                    "classification": classification,
                    "lexical_recovered": lexical_recovered,
                    "contextmesh_recovered": contextmesh_recovered,
                    "lexical_best_ground_truth_rank": (
                        12 if scale == 1 else 22
                    ),
                    "lexical_first_sufficient_rank": (
                        13 if scale == 1 else 26
                    ),
                    "lexical_failure_reason": (
                        "recovered"
                        if lexical_recovered
                        else "candidate-miss"
                    ),
                    "term_recall": (
                        1.0 if contextmesh_recovered else 0.0
                    ),
                    "coverage": 1.0,
                    "judgment_valid": True,
                    "latency_seconds": 0.2,
                }
            ]
        },
    }


def test_live_attribution_frontier_reports_shared_bottleneck_transition() -> None:
    points = [
        _point(
            1,
            classification="stable",
            lexical_recovered=True,
            contextmesh_recovered=True,
        ),
        _point(
            2,
            classification="shared-evidence-bottleneck",
            lexical_recovered=False,
            contextmesh_recovered=False,
        ),
    ]

    frontier = live_attribution_frontier(
        points,
        "cross-file-008",
        baseline="lexical-top-20",
    )

    assert frontier["status"] == "shared-retrieval-bottleneck"
    assert frontier["last_stable_scale"] == 1
    assert frontier["first_transition_scale"] == 2
    assert frontier["transition_bracket"] == {
        "greater_than": 1,
        "less_than_or_equal": 2,
    }
    assert frontier["transition"]["lexical_first_sufficient_rank"] == 26
    assert frontier["provider_call_performed"] is False


def test_live_attribution_frontier_distinguishes_contextmesh_rescue() -> None:
    points = [
        _point(
            1,
            classification="stable",
            lexical_recovered=True,
            contextmesh_recovered=True,
        ),
        _point(
            2,
            classification="contextmesh-recovery-win",
            lexical_recovered=False,
            contextmesh_recovered=True,
        ),
    ]

    frontier = live_attribution_frontier(
        points,
        "cross-file-008",
        baseline="lexical-top-20",
    )

    assert frontier["status"] == "contextmesh-rescues-retrieval"
    assert frontier["first_by_classification"][
        "contextmesh-recovery-win"
    ] == 2


def test_live_attribution_frontier_distinguishes_contextmesh_regression() -> None:
    points = [
        _point(
            1,
            classification="stable",
            lexical_recovered=True,
            contextmesh_recovered=True,
        ),
        _point(
            2,
            classification="contextmesh-regression",
            lexical_recovered=True,
            contextmesh_recovered=False,
        ),
    ]

    frontier = live_attribution_frontier(
        points,
        "cross-file-008",
        baseline="lexical-top-20",
    )

    assert frontier["status"] == (
        "contextmesh-regresses-despite-evidence"
    )
    assert frontier["transition"]["lexical_recovered"] is True
    assert frontier["transition"]["contextmesh_recovered"] is False


def test_live_attribution_frontier_stable_case_has_no_transition() -> None:
    points = [
        _point(
            1,
            classification="stable",
            lexical_recovered=True,
            contextmesh_recovered=True,
        ),
        _point(
            20,
            classification="stable",
            lexical_recovered=True,
            contextmesh_recovered=True,
        ),
    ]

    frontier = live_attribution_frontier(
        points,
        "cross-file-008",
    )

    assert frontier["status"] == "stable"
    assert frontier["first_transition_scale"] is None
    assert frontier["transition"] is None


def test_live_attribution_frontiers_emit_each_observed_baseline() -> None:
    points = [
        _point(
            1,
            classification="stable",
            lexical_recovered=True,
            contextmesh_recovered=True,
            baseline="lexical-top-5",
        ),
        _point(
            1,
            classification="stable",
            lexical_recovered=True,
            contextmesh_recovered=True,
            baseline="lexical-top-20",
        ),
    ]

    rows = live_attribution_frontiers(points)

    assert {
        (row["case_id"], row["baseline"])
        for row in rows
    } == {
        ("cross-file-008", "lexical-top-5"),
        ("cross-file-008", "lexical-top-20"),
    }


def test_compare_live_to_lexical_carries_retrieval_diagnostics() -> None:
    lexical = [
        {
            "case_id": "case",
            "recovered": False,
            "best_ground_truth_rank": 22,
            "first_sufficient_rank": 26,
            "failure_reason": "candidate-miss",
            "matched_terms": [],
            "matched_assets": [],
        }
    ]
    row = compare_live_to_lexical(
        lexical,
        [_live("case", False)],
    )[0]

    assert row["classification"] == "shared-evidence-bottleneck"
    assert row["lexical_best_ground_truth_rank"] == 22
    assert row["lexical_first_sufficient_rank"] == 26
    assert row["lexical_failure_reason"] == "candidate-miss"
