from __future__ import annotations

from copy import deepcopy

from benchmarks.verify_gate4_recovery_stability import verify_stability


def _curve(
    *,
    first_failure: float = 2.0,
    recovery_top_k: int = 26,
    recovered: bool = True,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "evidence_class": "contextmesh-gate4-offline-retrieval-baseline",
        "claim_scope": "retrieval-only",
        "provider_calls_made": 0,
        "model_tokens_billed": 0,
        "selected_case_ids": ["cross-file-008"],
        "anchor_fingerprint": "anchor",
        "points": [
            {
                "requested_ratio": 1.0,
                "actual_ratio": 1.0,
                "projection_fingerprint": "p1",
                "lexical_top_5_evidence_recall": 0.0,
                "lexical_top_20_evidence_recall": 1.0,
            },
            {
                "requested_ratio": 2.0,
                "actual_ratio": 2.0,
                "projection_fingerprint": "p2",
                "lexical_top_5_evidence_recall": 0.0,
                "lexical_top_20_evidence_recall": 0.0,
            },
        ],
        "failure_witnesses": [
            {
                "case_id": "cross-file-008",
                "kind": "cross-file",
                "top_5": {
                    "case_id": "cross-file-008",
                    "classification": "baseline-incapable",
                    "observed": True,
                    "previous_pass": None,
                    "failure": {
                        "scale": 1.0,
                        "best_ground_truth_rank": 12,
                        "first_sufficient_rank": 13,
                        "failure_reason": "candidate-miss",
                    },
                    "rank_shift": None,
                    "missing_terms": ["risk assessment"],
                    "missing_assets": [
                        "AI_RMF_Playbook.pdf",
                        "playbook.xlsx",
                    ],
                    "suggested_recovery_top_k": 13,
                    "intervention_verified": True,
                    "intervention_recovered": True,
                    "verified_recovery_top_k": 13,
                    "recovery_check": {
                        "recovered": True,
                        "evidence_scope": "offline-retrieval-only",
                    },
                    "live_model_recovery_verified": False,
                },
                "top_20": {
                    "case_id": "cross-file-008",
                    "classification": "scale-regression",
                    "observed": True,
                    "previous_pass": {
                        "scale": 1.0,
                    },
                    "failure": {
                        "scale": first_failure,
                        "best_ground_truth_rank": 22,
                        "first_sufficient_rank": recovery_top_k,
                        "failure_reason": "candidate-miss",
                    },
                    "rank_shift": {
                        "budget_shortfall": recovery_top_k - 20,
                    },
                    "missing_terms": ["risk assessment"],
                    "missing_assets": [
                        "AI_RMF_Playbook.pdf",
                        "playbook.xlsx",
                    ],
                    "suggested_recovery_top_k": recovery_top_k,
                    "intervention_verified": True,
                    "intervention_recovered": recovered,
                    "verified_recovery_top_k": recovery_top_k,
                    "recovery_check": {
                        "recovered": recovered,
                        "evidence_scope": "offline-retrieval-only",
                    },
                    "live_model_recovery_verified": False,
                },
            }
        ],
    }


def test_three_identical_runs_pass_recovery_stability() -> None:
    curves = [_curve(), _curve(), _curve()]

    result = verify_stability(
        curves,
        require_runs=3,
        require_case="cross-file-008",
        require_budget="top_20",
        require_first_failure_scale=2.0,
        require_recovery_verified=True,
    )

    assert result["stable"] is True
    assert result["blockers"] == []
    assert len(set(result["run_fingerprints"])) == 1
    assert result["required_witness"]["verified_recovery_top_k"] == 26


def test_witness_drift_fails_recovery_stability() -> None:
    curves = [_curve(), _curve(), _curve(recovery_top_k=27)]

    result = verify_stability(
        curves,
        require_runs=3,
        require_case="cross-file-008",
        require_first_failure_scale=2.0,
        require_recovery_verified=True,
    )

    assert result["stable"] is False
    assert any(
        "reproducibility-fingerprint-mismatch" in blocker
        for blocker in result["blockers"]
    )


def test_failure_onset_drift_fails_required_witness_contract() -> None:
    curves = [_curve(first_failure=5.0) for _ in range(3)]

    result = verify_stability(
        curves,
        require_runs=3,
        require_case="cross-file-008",
        require_first_failure_scale=2.0,
        require_recovery_verified=True,
    )

    assert result["stable"] is False
    assert any(
        blocker.startswith("required-first-failure-scale:")
        for blocker in result["blockers"]
    )


def test_unverified_or_failed_recovery_is_not_gate5_evidence() -> None:
    curves = [_curve(recovered=False) for _ in range(3)]

    result = verify_stability(
        curves,
        require_runs=3,
        require_case="cross-file-008",
        require_first_failure_scale=2.0,
        require_recovery_verified=True,
    )

    assert result["stable"] is False
    assert "required-recovery-did-not-recover" in result["blockers"]


def test_provider_usage_invalidates_offline_stability_claim() -> None:
    curves = [_curve(), _curve(), _curve()]
    curves[1] = deepcopy(curves[1])
    curves[1]["provider_calls_made"] = 1

    result = verify_stability(curves, require_runs=3)

    assert result["stable"] is False
    assert "run-2:provider-calls-not-zero" in result["blockers"]


def test_insufficient_repeated_runs_fail() -> None:
    result = verify_stability(
        [_curve(), _curve()],
        require_runs=3,
    )

    assert result["stable"] is False
    assert "runs:need>=3,got=2" in result["blockers"]
