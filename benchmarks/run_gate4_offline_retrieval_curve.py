from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from contextmesh.big_context_proof import (
    Gate4ScalePlanReport,
    _lexical_evidence_recall,
    _materialize_projection,
    load_needle_matrix,
)
from contextmesh.store import FileContextStore
from contextmesh.gate4_diagnostics import (
    failure_classification,
    failure_frontier,
    failure_witness,
    lexical_case_diagnostics,
)


def _fingerprint(block_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(block_ids).encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run a no-provider lexical retrieval curve over an exact frozen "
            "Gate 4 projection plan. This is baseline evidence, not Gate 4 PASS."
        )
    )
    ap.add_argument("corpus_id")
    ap.add_argument("--store", required=True)
    ap.add_argument("--needles", type=Path, required=True)
    ap.add_argument("--scale-plan", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args = ap.parse_args()

    store = FileContextStore(args.store)
    all_needles = load_needle_matrix(args.needles)
    plan = Gate4ScalePlanReport.model_validate_json(
        args.scale_plan.read_text(encoding="utf-8")
    )

    if plan.corpus_id != args.corpus_id:
        raise SystemExit(
            f"frozen plan corpus mismatch: {plan.corpus_id} != {args.corpus_id}"
        )
    if not plan.ready_for_live_gate4:
        raise SystemExit("frozen Gate 4 plan is not ready")
    if plan.blockers:
        raise SystemExit("frozen Gate 4 plan contains blockers")

    by_id = {case.id: case for case in all_needles}
    missing = [case_id for case_id in plan.selected_case_ids if case_id not in by_id]
    if missing:
        raise SystemExit(f"frozen plan references missing needle cases: {missing}")
    needles = [by_id[case_id] for case_id in plan.selected_case_ids]

    previous: set[str] = set()
    rows: list[dict[str, object]] = []
    for point in plan.points:
        current = set(point.block_ids)
        fingerprint = _fingerprint(point.block_ids)
        if fingerprint != point.projection_fingerprint:
            raise SystemExit(
                f"{point.requested_ratio:g}x projection fingerprint mismatch"
            )
        if not set(plan.anchor_block_ids).issubset(current):
            raise SystemExit(
                f"{point.requested_ratio:g}x projection lost frozen anchor evidence"
            )
        if previous and not previous.issubset(current):
            raise SystemExit(
                f"{point.requested_ratio:g}x projection is not nested"
            )
        previous = current

        with tempfile.TemporaryDirectory(prefix="contextmesh-offline-gate4-") as tmp:
            projected_store = FileContextStore(Path(tmp) / "store")
            projected_id = (
                f"{args.corpus_id}__offline_scale_"
                f"{str(point.requested_ratio).replace('.', '_')}"
            )
            manifest = _materialize_projection(
                store,
                args.corpus_id,
                projected_store,
                projected_id,
                list(point.block_ids),
            )
            top5 = _lexical_evidence_recall(
                projected_store, projected_id, needles, 5
            )
            top20 = _lexical_evidence_recall(
                projected_store, projected_id, needles, 20
            )
            diag5 = lexical_case_diagnostics(projected_store, projected_id, needles, 5)
            diag20 = lexical_case_diagnostics(projected_store, projected_id, needles, 20)

        rows.append(
            {
                "requested_ratio": point.requested_ratio,
                "actual_ratio": point.actual_ratio,
                "estimated_tokens": point.estimated_tokens,
                "selected_blocks": manifest.required_blocks,
                "selected_assets": len(manifest.assets),
                "projection_fingerprint": point.projection_fingerprint,
                "anchor_preserved": True,
                "nested_with_previous": point.nested_with_previous,
                "lexical_top_5_evidence_recall": top5,
                "lexical_top_20_evidence_recall": top20,
                "lexical_top_5_cases": diag5,
                "lexical_top_20_cases": diag20,
            }
        )

    first5 = float(rows[0]["lexical_top_5_evidence_recall"]) if rows else 0.0
    first20 = float(rows[0]["lexical_top_20_evidence_recall"]) if rows else 0.0
    min5 = min(
        (float(row["lexical_top_5_evidence_recall"]) for row in rows),
        default=0.0,
    )
    min20 = min(
        (float(row["lexical_top_20_evidence_recall"]) for row in rows),
        default=0.0,
    )

    payload = {
        "schema_version": 1,
        "evidence_class": "contextmesh-gate4-offline-retrieval-baseline",
        "claim_scope": (
            "No-provider retrieval-only scale curve over the exact frozen Gate 4 "
            "projections. This does not execute the live model and cannot pass Gate 4."
        ),
        "corpus_id": args.corpus_id,
        "provider_calls_made": 0,
        "model_tokens_billed": 0,
        "live_gate4_status": "not-run",
        "selected_case_ids": plan.selected_case_ids,
        "anchor_fingerprint": plan.anchor_fingerprint,
        "points": rows,
        "lexical_top_5_max_drop": first5 - min5,
        "lexical_top_20_max_drop": first20 - min20,
        "case_failures": [
            {
                "case_id": case.id,
                "kind": case.kind.value,
                "top_5": failure_classification(rows, case.id, "lexical_top_5_cases"),
                "top_20": failure_classification(rows, case.id, "lexical_top_20_cases"),
            }
            for case in needles if case.expected_present
        ],
        "failure_frontiers": [
            {
                "case_id": case.id,
                "kind": case.kind.value,
                "top_5": failure_frontier(
                    rows,
                    case.id,
                    "lexical_top_5_cases",
                    top_k=5,
                ),
                "top_20": failure_frontier(
                    rows,
                    case.id,
                    "lexical_top_20_cases",
                    top_k=20,
                ),
            }
            for case in needles if case.expected_present
        ],
        "failure_witnesses": [
            {
                "case_id": case.id,
                "kind": case.kind.value,
                "top_5": failure_witness(
                    rows,
                    case.id,
                    "lexical_top_5_cases",
                    top_k=5,
                    expected_terms=case.match_terms,
                    target_assets=case.target_assets,
                ),
                "top_20": failure_witness(
                    rows,
                    case.id,
                    "lexical_top_20_cases",
                    top_k=20,
                    expected_terms=case.match_terms,
                    target_assets=case.target_assets,
                ),
            }
            for case in needles if case.expected_present
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Gate 4 Offline Retrieval Baseline",
        "",
        "> Retrieval-only evidence. No provider/model call was made. "
        "This artifact cannot mark Gate 4 PASS.",
        "",
        "| Requested | Actual | Blocks | Assets | lexical top-5 | lexical top-20 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {requested_ratio:g}x | {actual_ratio:.4f}x | "
            "{selected_blocks} | {selected_assets} | {lexical_top_5_evidence_recall:.3f} | "
            "{lexical_top_20_evidence_recall:.3f} |".format(**row)
        )
    lines.extend([
        "",
        "## Case evidence sufficiency (lexical top-20)",
        "",
        "| Scale | Case | First hit | Sufficient rank | Result | Failure reason |",
        "| ---: | :--- | ---: | ---: | :---: | :--- |",
    ])
    for row in rows:
        for case in row["lexical_top_20_cases"]:
            if not case.get("expected_present", True):
                continue
            first_hit = case.get("best_ground_truth_rank")
            sufficient = case.get("first_sufficient_rank")
            lines.append(
                "| {scale:g}x | {case_id} | {first_hit} | {sufficient} | {result} | {reason} |".format(
                    scale=float(row["requested_ratio"]),
                    case_id=case.get("case_id"),
                    first_hit="—" if first_hit is None else first_hit,
                    sufficient="—" if sufficient is None else sufficient,
                    result="recovered" if case.get("recovered") else "miss",
                    reason=case.get("failure_reason") or "—",
                )
            )

    lines.extend([
        "",
        "## Observed failure frontiers",
        "",
        "| Case | Budget | Last recovered | First failure | Breakpoint bracket | Mechanism | Recovery top-k |",
        "| :--- | ---: | ---: | ---: | :--- | :--- | ---: |",
    ])
    for case in payload["failure_frontiers"]:
        for label, budget in (("top_5", 5), ("top_20", 20)):
            frontier = case[label]
            bracket = frontier.get("breakpoint_bracket")
            if bracket:
                bracket_text = (
                    f"({bracket['greater_than']:g}x, "
                    f"{bracket['less_than_or_equal']:g}x]"
                )
            else:
                bracket_text = "—"
            lines.append(
                "| {case_id} | {budget} | {last} | {first} | {bracket} | {mechanism} | {recovery} |".format(
                    case_id=case["case_id"],
                    budget=budget,
                    last="—" if frontier.get("last_recovered_scale") is None else f"{frontier['last_recovered_scale']:g}x",
                    first="—" if frontier.get("first_failure_scale") is None else f"{frontier['first_failure_scale']:g}x",
                    bracket=bracket_text,
                    mechanism=frontier.get("mechanism") or "—",
                    recovery="—" if frontier.get("recovery_top_k") is None else frontier["recovery_top_k"],
                )
            )

    lines.extend([
        "",
        "## Minimal observed failure witnesses",
        "",
        "> Suggested recovery top-k is diagnostic inference only. "
        "It is not a verified intervention until a separate run executes it.",
        "",
        "| Case | Budget | PASS scale | FAIL scale | First hit | Sufficient rank | Shortfall | Missing terms | Missing assets | Suggested top-k |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | ---: |",
    ])
    for case in payload["failure_witnesses"]:
        for label, budget in (("top_5", 5), ("top_20", 20)):
            witness = case[label]
            failure = witness.get("failure")
            previous = witness.get("previous_pass")
            if not failure:
                continue
            shortfall = (witness.get("rank_shift") or {}).get(
                "budget_shortfall"
            )
            lines.append(
                "| {case_id} | {budget} | {pass_scale} | {fail_scale} | "
                "{first_hit} | {sufficient} | {shortfall} | {terms} | "
                "{assets} | {suggested} |".format(
                    case_id=case["case_id"],
                    budget=budget,
                    pass_scale=(
                        "—"
                        if not previous
                        else f"{previous['scale']:g}x"
                    ),
                    fail_scale=f"{failure['scale']:g}x",
                    first_hit=(
                        "—"
                        if failure.get("best_ground_truth_rank") is None
                        else failure["best_ground_truth_rank"]
                    ),
                    sufficient=(
                        "—"
                        if failure.get("first_sufficient_rank") is None
                        else failure["first_sufficient_rank"]
                    ),
                    shortfall="—" if shortfall is None else shortfall,
                    terms=", ".join(witness.get("missing_terms") or []) or "—",
                    assets=", ".join(witness.get("missing_assets") or []) or "—",
                    suggested=(
                        "—"
                        if witness.get("suggested_recovery_top_k") is None
                        else witness["suggested_recovery_top_k"]
                    ),
                )
            )

    lines.extend(
        [
            "",
            f"Top-5 maximum drop: **{payload['lexical_top_5_max_drop']:.3f}**",
            f"Top-20 maximum drop: **{payload['lexical_top_20_max_drop']:.3f}**",
            "",
            "Live Gate 4 remains **NOT RUN** until an authorized provider route executes "
            "the same frozen projections.",
        ]
    )
    args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
