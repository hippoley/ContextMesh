from __future__ import annotations

from contextmesh.gate4_diagnostics import attach_recovery_confirmation, failure_frontier, failure_mechanism, failure_witness


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



def test_failure_witness_captures_pass_fail_transition_and_missing_evidence() -> None:
    points = [
        {
            "requested_ratio": 1,
            "lexical_top_20_cases": [
                {
                    **_diag(
                        recovered=True,
                        first_hit=2,
                        sufficient=8,
                    ),
                    "matched_terms": ["alpha", "beta"],
                    "matched_assets": ["a.txt", "b.txt"],
                }
            ],
        },
        {
            "requested_ratio": 2,
            "lexical_top_20_cases": [
                {
                    **_diag(
                        recovered=False,
                        first_hit=3,
                        sufficient=24,
                    ),
                    "matched_terms": ["alpha"],
                    "matched_assets": ["a.txt"],
                }
            ],
        },
    ]

    witness = failure_witness(
        points,
        "cross-file-008",
        "lexical_top_20_cases",
        top_k=20,
        expected_terms=["alpha", "beta"],
        target_assets=["a.txt", "b.txt"],
    )

    assert witness["classification"] == "scale-regression"
    assert witness["previous_pass"]["scale"] == 1
    assert witness["failure"]["scale"] == 2
    assert witness["failure"]["best_ground_truth_rank"] == 3
    assert witness["failure"]["first_sufficient_rank"] == 24
    assert witness["rank_shift"]["budget_shortfall"] == 4
    assert witness["missing_terms"] == ["beta"]
    assert witness["missing_assets"] == ["b.txt"]
    assert witness["suggested_recovery_top_k"] == 24
    assert witness["suggestion_evidence"] == "diagnostic-inference"
    assert witness["intervention_verified"] is False


def test_failure_witness_does_not_call_inferred_budget_a_verified_intervention() -> None:
    points = [
        {
            "requested_ratio": 1,
            "lexical_top_5_cases": [
                {
                    **_diag(
                        recovered=True,
                        first_hit=1,
                        sufficient=4,
                    ),
                    "matched_terms": ["needle"],
                    "matched_assets": ["a.txt"],
                }
            ],
        },
        {
            "requested_ratio": 5,
            "lexical_top_5_cases": [
                {
                    **_diag(
                        recovered=False,
                        first_hit=6,
                        sufficient=9,
                    ),
                    "matched_terms": [],
                    "matched_assets": [],
                }
            ],
        },
    ]

    witness = failure_witness(
        points,
        "cross-file-008",
        "lexical_top_5_cases",
        top_k=5,
        expected_terms=["needle"],
        target_assets=["a.txt"],
    )

    assert witness["suggested_recovery_top_k"] == 9
    assert witness["intervention_verified"] is False
    assert witness["suggestion_evidence"] == "diagnostic-inference"


def test_failure_witness_stable_case_has_no_failure_artifact() -> None:
    points = [
        {
            "requested_ratio": 1,
            "lexical_top_20_cases": [
                {
                    **_diag(
                        recovered=True,
                        first_hit=2,
                        sufficient=8,
                    ),
                    "matched_terms": ["alpha"],
                    "matched_assets": ["a.txt"],
                }
            ],
        },
        {
            "requested_ratio": 20,
            "lexical_top_20_cases": [
                {
                    **_diag(
                        recovered=True,
                        first_hit=5,
                        sufficient=15,
                    ),
                    "matched_terms": ["alpha"],
                    "matched_assets": ["a.txt"],
                }
            ],
        },
    ]

    witness = failure_witness(
        points,
        "cross-file-008",
        "lexical_top_20_cases",
        top_k=20,
        expected_terms=["alpha"],
        target_assets=["a.txt"],
    )

    assert witness["classification"] == "stable"
    assert witness["observed"] is False
    assert witness["failure"] is None
    assert witness["suggested_recovery_top_k"] is None



def test_attach_recovery_confirmation_requires_matching_scale_and_budget() -> None:
    witness = {
        "case_id": "cross-file-008",
        "top_k": 20,
        "failure": {"scale": 2.0},
        "intervention_verified": False,
    }
    checks = [
        {
            "case_id": "cross-file-008",
            "baseline_top_k": 20,
            "verified_recovery_top_k": 24,
            "intervention_verified": True,
            "recovered": True,
            "evidence_scope": "offline-retrieval-only",
        }
    ]

    wrong_scale = attach_recovery_confirmation(
        witness,
        scale=5.0,
        checks=checks,
    )
    assert wrong_scale["intervention_verified"] is False

    confirmed = attach_recovery_confirmation(
        witness,
        scale=2.0,
        checks=checks,
    )
    assert confirmed["intervention_verified"] is True
    assert confirmed["intervention_recovered"] is True
    assert confirmed["verified_recovery_top_k"] == 24
    assert confirmed["intervention_evidence_scope"] == (
        "offline-retrieval-only"
    )
    assert confirmed["live_model_recovery_verified"] is False


def test_attach_recovery_confirmation_does_not_use_wrong_budget() -> None:
    witness = {
        "case_id": "cross-file-008",
        "top_k": 20,
        "failure": {"scale": 2.0},
        "intervention_verified": False,
    }
    checks = [
        {
            "case_id": "cross-file-008",
            "baseline_top_k": 5,
            "verified_recovery_top_k": 9,
            "intervention_verified": True,
            "recovered": True,
            "evidence_scope": "offline-retrieval-only",
        }
    ]

    result = attach_recovery_confirmation(
        witness,
        scale=2.0,
        checks=checks,
    )

    assert result["intervention_verified"] is False
    assert "verified_recovery_top_k" not in result
