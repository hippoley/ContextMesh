from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from contextmesh.gate4_diagnostics import live_attribution_frontiers


def _gate4_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    gate4 = payload.get("gate4")
    if isinstance(gate4, dict):
        points = gate4.get("points")
    else:
        points = payload.get("points")
    if not isinstance(points, list):
        raise ValueError(
            "input must be a Gate4Report or a proof report containing gate4.points"
        )
    return [
        point
        for point in points
        if isinstance(point, dict)
    ]


def build_live_attribution_report(
    payload: dict[str, Any],
) -> dict[str, Any]:
    points = _gate4_points(payload)
    frontiers = live_attribution_frontiers(points)
    observed = [
        row
        for row in frontiers
        if row.get("status") != "not-observed"
    ]
    transitions = [
        row
        for row in observed
        if row.get("first_transition_scale") is not None
    ]
    counts = Counter(
        str(row.get("status"))
        for row in observed
    )
    baselines = sorted(
        {
            str(row.get("baseline"))
            for row in observed
        }
    )
    cases = sorted(
        {
            str(row.get("case_id"))
            for row in observed
        }
    )

    return {
        "schema_version": 1,
        "evidence_class": (
            "contextmesh-gate4-live-attribution-frontiers"
        ),
        "claim_scope": (
            "Re-analysis of already-scored Gate 4 live telemetry joined "
            "to lexical retrieval diagnostics. This command makes no "
            "provider call. Live evidence exists only if the input artifact "
            "came from an actual provider-backed Gate 4 run."
        ),
        "provider_calls_made_by_reporter": 0,
        "observed_cases": len(cases),
        "baselines": baselines,
        "status_counts": dict(sorted(counts.items())),
        "transition_count": len(transitions),
        "frontiers": frontiers,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Gate 4 Live Attribution Frontiers",
        "",
        "> This report re-analyzes existing Gate 4 telemetry. "
        "The reporter makes no provider call.",
        "",
        f"Observed cases: **{report['observed_cases']}**",
        f"Transitions: **{report['transition_count']}**",
        "",
        "## Attribution transitions",
        "",
        "| Case | Baseline | Status | Last stable | First transition | "
        "Lexical first hit | Sufficient rank |",
        "| :--- | :--- | :--- | ---: | ---: | ---: | ---: |",
    ]

    for row in report["frontiers"]:
        transition = row.get("transition") or {}
        if row.get("status") == "not-observed":
            continue
        lines.append(
            "| {case} | {baseline} | {status} | {last} | {first} | "
            "{hit} | {sufficient} |".format(
                case=row.get("case_id"),
                baseline=row.get("baseline"),
                status=row.get("status"),
                last=(
                    "—"
                    if row.get("last_stable_scale") is None
                    else f"{row['last_stable_scale']:g}x"
                ),
                first=(
                    "—"
                    if row.get("first_transition_scale") is None
                    else f"{row['first_transition_scale']:g}x"
                ),
                hit=(
                    "—"
                    if transition.get(
                        "lexical_best_ground_truth_rank"
                    )
                    is None
                    else transition[
                        "lexical_best_ground_truth_rank"
                    ]
                ),
                sufficient=(
                    "—"
                    if transition.get(
                        "lexical_first_sufficient_rank"
                    )
                    is None
                    else transition[
                        "lexical_first_sufficient_rank"
                    ]
                ),
            )
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Build Gate 4 live-vs-lexical attribution frontiers from "
            "an already-scored proof artifact."
        )
    )
    ap.add_argument("input", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args = ap.parse_args()

    payload = json.loads(
        args.input.read_text(encoding="utf-8")
    )
    report = build_live_attribution_report(payload)

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.markdown.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    args.markdown.write_text(
        render_markdown(report),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
