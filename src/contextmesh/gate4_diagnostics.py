from __future__ import annotations

from pathlib import Path
from typing import Any

from contextmesh.big_context_proof import (
    NeedleCase,
    NeedleKind,
    _ground_truth_block_matches,
    _term_hits,
)
from contextmesh.reader import CorpusReader
from contextmesh.store import FileContextStore


def lexical_case_diagnostics(
    store: FileContextStore,
    corpus_id: str,
    cases: list[NeedleCase],
    top_k: int,
) -> list[dict[str, Any]]:
    """Explain retrieval-only evidence recovery without changing the scorer."""
    reader = CorpusReader(store, corpus_id)
    out: list[dict[str, Any]] = []
    for case in cases:
        if not case.expected_present:
            out.append({
                "case_id": case.id,
                "kind": case.kind.value,
                "expected_present": False,
                "recovered": None,
                "best_ground_truth_rank": None,
                "ground_truth_ranks": [],
                "first_sufficient_rank": None,
                "failure_reason": "not-applicable",
                "matched_terms": [],
                "matched_assets": [],
            })
            continue

        ordered = reader.lexical_order(case.question)
        selected_ids = ordered[: max(0, top_k)]
        matched_terms: set[str] = set()
        matched_assets: set[str] = set()
        matched_target = False
        ground_truth_ranks: list[int] = []
        first_sufficient_rank: int | None = None

        required_asset_hits = case.required_asset_hits
        if required_asset_hits is None:
            required_asset_hits = (
                len(case.target_assets)
                if case.kind == NeedleKind.CROSS_FILE and case.target_assets
                else 1
            )

        cumulative_terms: set[str] = set()
        cumulative_assets: set[str] = set()
        for rank, block_id in enumerate(ordered, start=1):
            block = reader.read(block_id)
            if not _ground_truth_block_matches(block, case):
                continue
            ground_truth_ranks.append(rank)
            hits = _term_hits(block.text or "", case.match_terms)
            cumulative_terms.update(hits)
            if hits or not case.match_terms:
                cumulative_assets.add(Path(block.source.path).name)
            if case.match_terms:
                cumulative_terms_ok = (
                    len(cumulative_terms) == len(set(case.match_terms))
                    if case.match_all_terms
                    else bool(cumulative_terms)
                )
            else:
                cumulative_terms_ok = True
            if cumulative_terms_ok and len(cumulative_assets) >= required_asset_hits:
                first_sufficient_rank = rank
                break

        for block_id in selected_ids:
            block = reader.read(block_id)
            if not _ground_truth_block_matches(block, case):
                continue
            matched_target = True
            hits = _term_hits(block.text or "", case.match_terms)
            matched_terms.update(hits)
            if hits or not case.match_terms:
                matched_assets.add(Path(block.source.path).name)

        if case.match_terms:
            terms_ok = (
                len(matched_terms) == len(set(case.match_terms))
                if case.match_all_terms
                else bool(matched_terms)
            )
        else:
            terms_ok = matched_target

        assets_ok = len(matched_assets) >= required_asset_hits
        if terms_ok and assets_ok:
            failure_reason = "recovered"
        elif not matched_target:
            failure_reason = "candidate-miss"
        elif not terms_ok:
            failure_reason = "term-miss"
        else:
            failure_reason = "asset-miss"

        out.append({
            "case_id": case.id,
            "kind": case.kind.value,
            "modality": getattr(case, "modality", None),
            "corpus_position": getattr(case, "corpus_position", None),
            "local_position": getattr(case, "local_position", None),
            "expected_present": True,
            "recovered": bool(terms_ok and assets_ok),
            "best_ground_truth_rank": ground_truth_ranks[0] if ground_truth_ranks else None,
            "ground_truth_ranks": ground_truth_ranks,
            "first_sufficient_rank": first_sufficient_rank,
            "failure_reason": failure_reason,
            "matched_terms": sorted(matched_terms),
            "matched_assets": sorted(matched_assets),
            "required_asset_hits": required_asset_hits,
        })
    return out



def failure_classification(
    points: list[dict[str, Any]], case_id: str, key: str
) -> dict[str, Any]:
    observations = [
        (float(point["requested_ratio"]), next(
            (x for x in point[key] if x["case_id"] == case_id), None
        ))
        for point in points
    ]
    present = [(ratio, diag) for ratio, diag in observations if diag and diag["expected_present"]]
    if not present:
        return {"classification": "not-applicable", "first_failure_scale": None}
    first_ratio, first_diag = present[0]
    if not first_diag["recovered"]:
        return {"classification": "baseline-incapable", "first_failure_scale": first_ratio}
    for ratio, diag in present[1:]:
        if not diag["recovered"]:
            return {"classification": "scale-regression", "first_failure_scale": ratio}
    return {"classification": "stable", "first_failure_scale": None}


def compare_live_to_lexical(
    lexical_cases: list[dict[str, Any]],
    live_results: list[Any],
) -> list[dict[str, Any]]:
    """Join already-scored live results to retrieval diagnostics without re-judging."""
    lexical_by_id = {row["case_id"]: row for row in lexical_cases}
    out: list[dict[str, Any]] = []
    for live in live_results:
        if not live.expected_present:
            continue
        lexical = lexical_by_id.get(live.case_id)
        lexical_recovered = None if lexical is None else lexical.get("recovered")
        if lexical_recovered is False and live.recovered:
            classification = "contextmesh-recovery-win"
        elif lexical_recovered is True and not live.recovered:
            classification = "contextmesh-regression"
        elif lexical_recovered is False and not live.recovered:
            classification = "shared-evidence-bottleneck"
        elif lexical_recovered is True and live.recovered:
            classification = "stable"
        else:
            classification = "baseline-unavailable"
        out.append({
            "case_id": live.case_id,
            "kind": live.kind.value,
            "lexical_recovered": lexical_recovered,
            "contextmesh_recovered": live.recovered,
            "term_recall": live.term_recall,
            "coverage": live.coverage,
            "visited_blocks": live.visited_blocks,
            "total_blocks": live.total_blocks,
            "judgment_valid": live.judgment_valid,
            "latency_seconds": live.latency_seconds,
            "classification": classification,
            "lexical_best_ground_truth_rank": (
                None
                if lexical is None
                else lexical.get("best_ground_truth_rank")
            ),
            "lexical_first_sufficient_rank": (
                None
                if lexical is None
                else lexical.get("first_sufficient_rank")
            ),
            "lexical_failure_reason": (
                None
                if lexical is None
                else lexical.get("failure_reason")
            ),
            "lexical_matched_terms": (
                []
                if lexical is None
                else list(lexical.get("matched_terms") or [])
            ),
            "lexical_matched_assets": (
                []
                if lexical is None
                else list(lexical.get("matched_assets") or [])
            ),
        })
    return out



def failure_mechanism(diag: dict[str, Any], *, top_k: int) -> dict[str, Any]:
    """Classify why a lexical case failed at a fixed retrieval budget."""
    if not diag.get("expected_present", True):
        return {
            "mechanism": "not-applicable",
            "recovery_top_k": None,
            "rank_gap": None,
        }
    if diag.get("recovered"):
        return {
            "mechanism": "recovered",
            "recovery_top_k": diag.get("first_sufficient_rank"),
            "rank_gap": 0,
        }

    first_hit = diag.get("best_ground_truth_rank")
    sufficient = diag.get("first_sufficient_rank")
    if first_hit is None:
        mechanism = "ground-truth-displaced"
    elif first_hit > top_k:
        mechanism = "first-hit-beyond-budget"
    elif sufficient is None:
        mechanism = "evidence-closure-unresolved"
    elif sufficient > top_k:
        mechanism = "partial-evidence-below-sufficiency"
    else:
        mechanism = diag.get("failure_reason") or "unclassified"

    return {
        "mechanism": mechanism,
        "recovery_top_k": sufficient,
        "rank_gap": None if sufficient is None else max(0, sufficient - top_k),
    }


def failure_frontier(
    points: list[dict[str, Any]],
    case_id: str,
    key: str,
    *,
    top_k: int,
) -> dict[str, Any]:
    """Locate the first observed scale failure and explain its retrieval mechanism.

    This reports an observed bracket over the frozen scale points; it does not
    interpolate an unmeasured exact breakpoint.
    """
    present: list[tuple[float, dict[str, Any]]] = []
    for point in points:
        diag = next(
            (row for row in point.get(key, []) if row.get("case_id") == case_id),
            None,
        )
        if diag and diag.get("expected_present"):
            present.append((float(point["requested_ratio"]), diag))

    if not present:
        return {
            "classification": "not-applicable",
            "last_recovered_scale": None,
            "first_failure_scale": None,
            "breakpoint_bracket": None,
            "mechanism": "not-applicable",
            "recovery_top_k": None,
            "rank_gap": None,
        }

    last_recovered: float | None = None
    first_failure: tuple[float, dict[str, Any]] | None = None
    for ratio, diag in present:
        if diag.get("recovered"):
            last_recovered = ratio
            continue
        first_failure = (ratio, diag)
        break

    if first_failure is None:
        return {
            "classification": "stable",
            "last_recovered_scale": last_recovered,
            "first_failure_scale": None,
            "breakpoint_bracket": None,
            "mechanism": "recovered",
            "recovery_top_k": None,
            "rank_gap": 0,
        }

    failure_ratio, failure_diag = first_failure
    mechanism = failure_mechanism(failure_diag, top_k=top_k)
    baseline_failed = last_recovered is None
    bracket = (
        None
        if baseline_failed
        else {
            "greater_than": last_recovered,
            "less_than_or_equal": failure_ratio,
        }
    )
    return {
        "classification": "baseline-incapable" if baseline_failed else "scale-regression",
        "last_recovered_scale": last_recovered,
        "first_failure_scale": failure_ratio,
        "breakpoint_bracket": bracket,
        **mechanism,
    }



def failure_witness(
    points: list[dict[str, Any]],
    case_id: str,
    key: str,
    *,
    top_k: int,
    expected_terms: list[str] | None = None,
    target_assets: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal observed PASS->FAIL witness for one retrieval case.

    The suggested recovery budget is an inference from the observed ranking.
    It is not labeled as a successful intervention until a separate run
    actually executes that budget.
    """
    observations: list[tuple[float, dict[str, Any]]] = []
    for point in points:
        diag = next(
            (
                row
                for row in point.get(key, [])
                if row.get("case_id") == case_id
            ),
            None,
        )
        if diag and diag.get("expected_present"):
            observations.append(
                (float(point["requested_ratio"]), diag)
            )

    previous_pass: tuple[float, dict[str, Any]] | None = None
    for ratio, diag in observations:
        if diag.get("recovered"):
            previous_pass = (ratio, diag)
            continue
        if previous_pass is None:
            return {
                "case_id": case_id,
                "top_k": top_k,
                "classification": "baseline-incapable",
                "observed": True,
                "previous_pass": None,
                "failure": {
                    "scale": ratio,
                    "best_ground_truth_rank": diag.get(
                        "best_ground_truth_rank"
                    ),
                    "first_sufficient_rank": diag.get(
                        "first_sufficient_rank"
                    ),
                    "failure_reason": diag.get(
                        "failure_reason"
                    ),
                    "matched_terms": list(
                        diag.get("matched_terms") or []
                    ),
                    "matched_assets": list(
                        diag.get("matched_assets") or []
                    ),
                },
                "missing_terms": sorted(
                    set(expected_terms or [])
                    - set(diag.get("matched_terms") or [])
                ),
                "missing_assets": sorted(
                    {
                        Path(asset).name
                        for asset in (target_assets or [])
                    }
                    - set(diag.get("matched_assets") or [])
                ),
                "suggested_recovery_top_k": diag.get(
                    "first_sufficient_rank"
                ),
                "suggestion_evidence": "diagnostic-inference",
                "intervention_verified": False,
            }

        pass_ratio, pass_diag = previous_pass
        sufficient = diag.get("first_sufficient_rank")
        witness = {
            "case_id": case_id,
            "top_k": top_k,
            "classification": "scale-regression",
            "observed": True,
            "previous_pass": {
                "scale": pass_ratio,
                "best_ground_truth_rank": pass_diag.get(
                    "best_ground_truth_rank"
                ),
                "first_sufficient_rank": pass_diag.get(
                    "first_sufficient_rank"
                ),
                "matched_terms": list(
                    pass_diag.get("matched_terms") or []
                ),
                "matched_assets": list(
                    pass_diag.get("matched_assets") or []
                ),
            },
            "failure": {
                "scale": ratio,
                "best_ground_truth_rank": diag.get(
                    "best_ground_truth_rank"
                ),
                "first_sufficient_rank": sufficient,
                "failure_reason": diag.get(
                    "failure_reason"
                ),
                "matched_terms": list(
                    diag.get("matched_terms") or []
                ),
                "matched_assets": list(
                    diag.get("matched_assets") or []
                ),
            },
            "rank_shift": {
                "best_ground_truth_rank_delta": (
                    None
                    if (
                        pass_diag.get("best_ground_truth_rank")
                        is None
                        or diag.get("best_ground_truth_rank")
                        is None
                    )
                    else (
                        int(diag["best_ground_truth_rank"])
                        - int(pass_diag["best_ground_truth_rank"])
                    )
                ),
                "sufficient_rank_delta": (
                    None
                    if (
                        pass_diag.get("first_sufficient_rank")
                        is None
                        or sufficient is None
                    )
                    else (
                        int(sufficient)
                        - int(
                            pass_diag["first_sufficient_rank"]
                        )
                    )
                ),
                "budget_shortfall": (
                    None
                    if sufficient is None
                    else max(0, int(sufficient) - top_k)
                ),
            },
            "missing_terms": sorted(
                set(expected_terms or [])
                - set(diag.get("matched_terms") or [])
            ),
            "missing_assets": sorted(
                {
                    Path(asset).name
                    for asset in (target_assets or [])
                }
                - set(diag.get("matched_assets") or [])
            ),
            "suggested_recovery_top_k": sufficient,
            "suggestion_evidence": "diagnostic-inference",
            "intervention_verified": False,
        }
        return witness

    return {
        "case_id": case_id,
        "top_k": top_k,
        "classification": "stable",
        "observed": False,
        "previous_pass": (
            None
            if previous_pass is None
            else {
                "scale": previous_pass[0],
                "best_ground_truth_rank": previous_pass[1].get(
                    "best_ground_truth_rank"
                ),
                "first_sufficient_rank": previous_pass[1].get(
                    "first_sufficient_rank"
                ),
                "matched_terms": list(
                    previous_pass[1].get("matched_terms") or []
                ),
                "matched_assets": list(
                    previous_pass[1].get("matched_assets") or []
                ),
            }
        ),
        "failure": None,
        "missing_terms": [],
        "missing_assets": [],
        "suggested_recovery_top_k": None,
        "suggestion_evidence": None,
        "intervention_verified": False,
    }



def lexical_recovery_checks(
    store: FileContextStore,
    corpus_id: str,
    cases: list[NeedleCase],
    diagnostics: list[dict[str, Any]],
    *,
    baseline_top_k: int,
) -> list[dict[str, Any]]:
    """Actually rerun failed lexical cases at their observed sufficient rank.

    This verifies a retrieval-budget intervention on the same frozen projection.
    It remains retrieval-only evidence and does not imply live model recovery.
    """
    by_id = {case.id: case for case in cases}
    checks: list[dict[str, Any]] = []

    for diag in diagnostics:
        if not diag.get("expected_present"):
            continue
        if diag.get("recovered"):
            continue

        case_id = str(diag.get("case_id") or "")
        case = by_id.get(case_id)
        suggested = diag.get("first_sufficient_rank")
        if (
            case is None
            or suggested is None
            or int(suggested) <= baseline_top_k
        ):
            continue

        recovery_top_k = int(suggested)
        rerun = lexical_case_diagnostics(
            store,
            corpus_id,
            [case],
            recovery_top_k,
        )[0]
        checks.append({
            "case_id": case_id,
            "baseline_top_k": baseline_top_k,
            "verified_recovery_top_k": recovery_top_k,
            "intervention_type": "retrieval-budget-increase",
            "intervention_verified": True,
            "recovered": bool(rerun.get("recovered")),
            "failure_reason": rerun.get("failure_reason"),
            "best_ground_truth_rank": rerun.get(
                "best_ground_truth_rank"
            ),
            "first_sufficient_rank": rerun.get(
                "first_sufficient_rank"
            ),
            "matched_terms": list(
                rerun.get("matched_terms") or []
            ),
            "matched_assets": list(
                rerun.get("matched_assets") or []
            ),
            "evidence_scope": "offline-retrieval-only",
            "live_model_recovery_verified": False,
        })

    return checks


def attach_recovery_confirmation(
    witness: dict[str, Any],
    *,
    scale: float,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach an actually rerun retrieval intervention to a failure witness."""
    out = dict(witness)
    failure = witness.get("failure")
    if not failure or float(failure.get("scale")) != float(scale):
        return out

    check = next(
        (
            row
            for row in checks
            if row.get("case_id") == witness.get("case_id")
            and int(row.get("baseline_top_k") or -1)
            == int(witness.get("top_k") or -2)
        ),
        None,
    )
    if check is None:
        return out

    out["intervention_verified"] = True
    out["intervention_recovered"] = bool(
        check.get("recovered")
    )
    out["verified_recovery_top_k"] = check.get(
        "verified_recovery_top_k"
    )
    out["intervention_evidence_scope"] = check.get(
        "evidence_scope"
    )
    out["live_model_recovery_verified"] = False
    out["recovery_check"] = check
    return out



def live_attribution_frontier(
    points: list[Any],
    case_id: str,
    *,
    baseline: str = "lexical-top-20",
) -> dict[str, Any]:
    """Summarize the first observed live-vs-lexical attribution transition.

    This consumes already-scored Gate 4 point telemetry. It never invokes a
    provider and must not be used to claim live evidence unless the input points
    came from an actual live Gate 4 execution.
    """
    observations: list[dict[str, Any]] = []
    for point in points:
        if hasattr(point, "model_dump"):
            raw = point.model_dump(mode="json")
        elif isinstance(point, dict):
            raw = point
        else:
            continue

        attribution = raw.get("case_attribution") or {}
        rows = attribution.get(baseline) or []
        row = next(
            (
                item
                for item in rows
                if item.get("case_id") == case_id
            ),
            None,
        )
        if row is None:
            continue

        observations.append({
            "scale": float(raw.get("requested_ratio", 0.0)),
            "point_status": (
                raw.get("status")
                if isinstance(raw.get("status"), str)
                else getattr(raw.get("status"), "value", raw.get("status"))
            ),
            "classification": row.get("classification"),
            "lexical_recovered": row.get("lexical_recovered"),
            "contextmesh_recovered": row.get(
                "contextmesh_recovered"
            ),
            "lexical_best_ground_truth_rank": row.get(
                "lexical_best_ground_truth_rank"
            ),
            "lexical_first_sufficient_rank": row.get(
                "lexical_first_sufficient_rank"
            ),
            "lexical_failure_reason": row.get(
                "lexical_failure_reason"
            ),
            "term_recall": row.get("term_recall"),
            "coverage": row.get("coverage"),
            "judgment_valid": row.get("judgment_valid"),
            "latency_seconds": row.get("latency_seconds"),
        })

    observations.sort(key=lambda row: row["scale"])
    first_by_classification: dict[str, float] = {}
    last_stable_before_transition: float | None = None
    first_non_stable: dict[str, Any] | None = None

    for row in observations:
        classification = str(
            row.get("classification") or "unknown"
        )
        first_by_classification.setdefault(
            classification,
            float(row["scale"]),
        )
        if classification == "stable":
            if first_non_stable is None:
                last_stable_before_transition = float(
                    row["scale"]
                )
        elif (
            classification != "baseline-unavailable"
            and first_non_stable is None
        ):
            first_non_stable = row

    if not observations:
        status = "not-observed"
    elif first_non_stable is None:
        status = "stable"
    elif (
        first_non_stable["classification"]
        == "contextmesh-recovery-win"
    ):
        status = "contextmesh-rescues-retrieval"
    elif (
        first_non_stable["classification"]
        == "contextmesh-regression"
    ):
        status = "contextmesh-regresses-despite-evidence"
    elif (
        first_non_stable["classification"]
        == "shared-evidence-bottleneck"
    ):
        status = "shared-retrieval-bottleneck"
    else:
        status = str(first_non_stable["classification"])

    first_transition_scale = (
        None
        if first_non_stable is None
        else float(first_non_stable["scale"])
    )
    transition_bracket = (
        None
        if (
            first_transition_scale is None
            or last_stable_before_transition is None
            or last_stable_before_transition >= first_transition_scale
        )
        else {
            "greater_than": last_stable_before_transition,
            "less_than_or_equal": first_transition_scale,
        }
    )

    return {
        "case_id": case_id,
        "baseline": baseline,
        "status": status,
        "observed_scales": [
            row["scale"] for row in observations
        ],
        "last_stable_scale": last_stable_before_transition,
        "first_transition_scale": first_transition_scale,
        "transition_bracket": transition_bracket,
        "first_by_classification": dict(
            sorted(first_by_classification.items())
        ),
        "transition": first_non_stable,
        "observations": observations,
        "evidence_scope": "already-scored-live-telemetry",
        "provider_call_performed": False,
    }


def live_attribution_frontiers(
    points: list[Any],
    *,
    baselines: tuple[str, ...] = (
        "lexical-top-5",
        "lexical-top-20",
    ),
) -> list[dict[str, Any]]:
    """Build attribution frontiers for every observed case/baseline pair."""
    case_ids: set[str] = set()
    for point in points:
        raw = (
            point.model_dump(mode="json")
            if hasattr(point, "model_dump")
            else point
        )
        if not isinstance(raw, dict):
            continue
        attribution = raw.get("case_attribution") or {}
        for baseline in baselines:
            for row in attribution.get(baseline) or []:
                case_id = row.get("case_id")
                if case_id:
                    case_ids.add(str(case_id))

    return [
        live_attribution_frontier(
            points,
            case_id,
            baseline=baseline,
        )
        for case_id in sorted(case_ids)
        for baseline in baselines
    ]
