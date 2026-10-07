from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _normalized_curve(payload: dict[str, Any]) -> dict[str, Any]:
    points = [
        {
            "requested_ratio": float(point["requested_ratio"]),
            "actual_ratio": float(point["actual_ratio"]),
            "projection_fingerprint": point["projection_fingerprint"],
            "lexical_top_5_evidence_recall": float(
                point["lexical_top_5_evidence_recall"]
            ),
            "lexical_top_20_evidence_recall": float(
                point["lexical_top_20_evidence_recall"]
            ),
        }
        for point in payload.get("points", [])
    ]

    witnesses: list[dict[str, Any]] = []
    for case in payload.get("failure_witnesses", []):
        for budget in ("top_5", "top_20"):
            witness = case.get(budget) or {}
            failure = witness.get("failure") or {}
            previous = witness.get("previous_pass") or {}
            rank_shift = witness.get("rank_shift") or {}
            recovery = witness.get("recovery_check") or {}
            witnesses.append(
                {
                    "case_id": case.get("case_id"),
                    "kind": case.get("kind"),
                    "budget": budget,
                    "classification": witness.get("classification"),
                    "observed": witness.get("observed"),
                    "previous_pass_scale": previous.get("scale"),
                    "failure_scale": failure.get("scale"),
                    "best_ground_truth_rank": failure.get(
                        "best_ground_truth_rank"
                    ),
                    "first_sufficient_rank": failure.get(
                        "first_sufficient_rank"
                    ),
                    "failure_reason": failure.get("failure_reason"),
                    "budget_shortfall": rank_shift.get(
                        "budget_shortfall"
                    ),
                    "missing_terms": sorted(
                        witness.get("missing_terms") or []
                    ),
                    "missing_assets": sorted(
                        witness.get("missing_assets") or []
                    ),
                    "suggested_recovery_top_k": witness.get(
                        "suggested_recovery_top_k"
                    ),
                    "intervention_verified": witness.get(
                        "intervention_verified"
                    ),
                    "intervention_recovered": witness.get(
                        "intervention_recovered"
                    ),
                    "verified_recovery_top_k": witness.get(
                        "verified_recovery_top_k"
                    ),
                    "recovery_check_recovered": recovery.get(
                        "recovered"
                    ),
                    "recovery_check_scope": recovery.get(
                        "evidence_scope"
                    ),
                    "live_model_recovery_verified": witness.get(
                        "live_model_recovery_verified"
                    ),
                }
            )

    return {
        "schema_version": payload.get("schema_version"),
        "evidence_class": payload.get("evidence_class"),
        "claim_scope": payload.get("claim_scope"),
        "provider_calls_made": payload.get("provider_calls_made"),
        "model_tokens_billed": payload.get("model_tokens_billed"),
        "selected_case_ids": payload.get("selected_case_ids"),
        "anchor_fingerprint": payload.get("anchor_fingerprint"),
        "points": points,
        "failure_witnesses": sorted(
            witnesses,
            key=lambda row: (
                str(row["case_id"]),
                str(row["budget"]),
            ),
        ),
    }


def _find_witness(
    normalized: dict[str, Any],
    case_id: str,
    budget: str,
) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in normalized.get("failure_witnesses", [])
            if row.get("case_id") == case_id
            and row.get("budget") == budget
        ),
        None,
    )


def verify_stability(
    curves: list[dict[str, Any]],
    *,
    require_runs: int = 3,
    require_case: str | None = None,
    require_budget: str = "top_20",
    require_first_failure_scale: float | None = None,
    require_recovery_verified: bool = False,
) -> dict[str, Any]:
    blockers: list[str] = []
    if len(curves) < require_runs:
        blockers.append(
            f"runs:need>={require_runs},got={len(curves)}"
        )

    normalized = [_normalized_curve(curve) for curve in curves]
    fingerprints = [_fingerprint(curve) for curve in normalized]
    baseline = normalized[0] if normalized else None
    baseline_fp = fingerprints[0] if fingerprints else None

    for index, curve in enumerate(curves, start=1):
        if curve.get("provider_calls_made") != 0:
            blockers.append(
                f"run-{index}:provider-calls-not-zero"
            )
        if curve.get("model_tokens_billed") != 0:
            blockers.append(
                f"run-{index}:model-tokens-not-zero"
            )

    for index, fingerprint in enumerate(
        fingerprints[1:],
        start=2,
    ):
        if fingerprint != baseline_fp:
            blockers.append(
                f"run-{index}:reproducibility-fingerprint-mismatch"
            )

    required_witness: dict[str, Any] | None = None
    if baseline is not None and require_case:
        required_witness = _find_witness(
            baseline,
            require_case,
            require_budget,
        )
        if required_witness is None:
            blockers.append(
                f"required-witness-missing:{require_case}:{require_budget}"
            )
        else:
            if (
                require_first_failure_scale is not None
                and required_witness.get("failure_scale")
                != require_first_failure_scale
            ):
                blockers.append(
                    "required-first-failure-scale:"
                    f"need={require_first_failure_scale:g},"
                    f"got={required_witness.get('failure_scale')}"
                )
            if require_recovery_verified:
                if (
                    required_witness.get("intervention_verified")
                    is not True
                ):
                    blockers.append(
                        "required-recovery-intervention-not-verified"
                    )
                if (
                    required_witness.get("intervention_recovered")
                    is not True
                ):
                    blockers.append(
                        "required-recovery-did-not-recover"
                    )
                if (
                    required_witness.get(
                        "live_model_recovery_verified"
                    )
                    is not False
                ):
                    blockers.append(
                        "offline-recovery-scope-claim-invalid"
                    )

    return {
        "schema_version": 1,
        "evidence_class": (
            "contextmesh-gate4-offline-recovery-stability"
        ),
        "claim_scope": (
            "Repeated no-provider retrieval-only runs over the same "
            "frozen Gate 4 corpus/plan. This establishes deterministic "
            "offline recovery reproducibility, not live-model Gate 4 "
            "attribution or Gate 5 completion."
        ),
        "runs": len(curves),
        "required_runs": require_runs,
        "stable": not blockers,
        "blockers": blockers,
        "run_fingerprints": fingerprints,
        "reproducibility_fingerprint": (
            baseline_fp if not blockers else None
        ),
        "required_witness": required_witness,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Verify repeated Gate 4 offline retrieval/recovery runs "
            "produce the same observed failure and recovery evidence."
        )
    )
    ap.add_argument(
        "curves",
        nargs="+",
        type=Path,
    )
    ap.add_argument("--require-runs", type=int, default=3)
    ap.add_argument("--require-case")
    ap.add_argument(
        "--require-budget",
        choices=["top_5", "top_20"],
        default="top_20",
    )
    ap.add_argument(
        "--require-first-failure-scale",
        type=float,
    )
    ap.add_argument(
        "--require-recovery-verified",
        action="store_true",
    )
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    curves = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in args.curves
    ]
    result = verify_stability(
        curves,
        require_runs=args.require_runs,
        require_case=args.require_case,
        require_budget=args.require_budget,
        require_first_failure_scale=(
            args.require_first_failure_scale
        ),
        require_recovery_verified=args.require_recovery_verified,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["stable"]:
        raise SystemExit(
            "GATE4_RECOVERY_STABILITY_FAIL:"
            + ";".join(result["blockers"])
        )
    print("GATE4_RECOVERY_STABILITY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
