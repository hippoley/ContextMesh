from __future__ import annotations

from typing import Any


def build_evidence_report(
    live_proof: dict[str, Any] | None,
    gate5_diff: dict[str, Any] | None = None,
) -> str:
    if not isinstance(live_proof, dict):
        return "# Big Context Evidence Report\n\nStatus: **LIVE PROOF NOT RUN**\n"
    gate3 = live_proof.get("gate3") or {}
    gate4 = live_proof.get("gate4") or {}
    lines = [
        "# Big Context Evidence Report",
        "",
        "This is a reviewer-facing index of already-scored evidence. It does not re-judge or change gate policy.",
        "",
        "## Gate Status",
        "",
        "| Gate | Status |",
        "|:---|:---|",
        "| Gate 3 | " + str(gate3.get("status") or "not-run").upper() + " |",
        "| Gate 4 | " + str(gate4.get("status") or "not-run").upper() + " |",
    ]
    if isinstance(gate5_diff, dict):
        lines.append("| Gate 5 | " + str(gate5_diff.get("status") or "not-run").upper() + " |")
    else:
        lines.append("| Gate 5 | NOT RUN |")

    points = [p for p in gate4.get("points") or [] if isinstance(p, dict)]
    if points:
        lines += [
            "",
            "## Gate 4 Scale Evidence",
            "",
            "| Scale | ContextMesh recall | Lexical@20 | Recovery wins | Regressions |",
            "|---:|---:|---:|---:|---:|",
        ]
        for point in points:
            attrs = (point.get("case_attribution") or {}).get("lexical-top-20") or []
            wins = sum(1 for row in attrs if row.get("classification") == "contextmesh-recovery-win")
            regressions = sum(1 for row in attrs if row.get("classification") == "contextmesh-regression")
            baseline = point.get("baseline_evidence_recall") or {}
            lines.append(
                "| {} | {} | {} | {} | {} |".format(
                    point.get("requested_ratio"),
                    point.get("evidence_recall"),
                    baseline.get("lexical-top-20"),
                    wins,
                    regressions,
                )
            )

    if isinstance(gate5_diff, dict):
        onset = (gate5_diff.get("scale_case_drift") or {}).get("failure_onset") or []
        earlier = [row for row in onset if row.get("classification") == "failure-onset-earlier"]
        later = [row for row in onset if row.get("classification") == "failure-onset-later"]
        lines += [
            "",
            "## Gate 5 Capability Boundary Drift",
            "",
            "- Failure onset earlier: **{}**".format(len(earlier)),
            "- Failure onset later: **{}**".format(len(later)),
        ]
        if earlier:
            lines += ["", "### Regressed boundaries", ""]
            for row in earlier:
                lines.append(
                    "- {}: {}x -> {}x".format(
                        row.get("case_id"),
                        row.get("reference_first_failure_ratio"),
                        row.get("candidate_first_failure_ratio"),
                    )
                )

    blockers = list(gate4.get("blockers") or [])
    if blockers:
        lines += ["", "## Gate 4 Blockers", ""]
        lines.extend("- " + str(item) for item in blockers)
    lines += [
        "",
        "## Claim Boundary",
        "",
        "This report summarizes existing proof artifacts only. PREPARED is not PASS, missing live evidence remains NOT RUN, and diagnostic classifications do not override Gate 3/4/5 thresholds.",
        "",
    ]
    return "\n".join(lines)


def build_evidence_summary(
    live_proof: dict[str, Any] | None,
    gate5_diff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(live_proof, dict):
        return {
            "schema_version": 1,
            "status": "not-run",
            "gates": {},
            "provenance": {"live_proof": "missing", "gate5_diff": "missing"},
        }
    gate3 = live_proof.get("gate3") or {}
    gate4 = live_proof.get("gate4") or {}
    points = [p for p in gate4.get("points") or [] if isinstance(p, dict)]
    scale = []
    for point in points:
        attrs = (point.get("case_attribution") or {}).get("lexical-top-20") or []
        scale.append({
            "requested_ratio": point.get("requested_ratio"),
            "status": point.get("status"),
            "contextmesh_evidence_recall": point.get("evidence_recall"),
            "lexical_top_20_evidence_recall": (
                point.get("baseline_evidence_recall") or {}
            ).get("lexical-top-20"),
            "contextmesh_recovery_wins": sum(
                1 for row in attrs
                if row.get("classification") == "contextmesh-recovery-win"
            ),
            "contextmesh_regressions": sum(
                1 for row in attrs
                if row.get("classification") == "contextmesh-regression"
            ),
        })
    onset = (
        (gate5_diff.get("scale_case_drift") or {}).get("failure_onset") or []
        if isinstance(gate5_diff, dict)
        else []
    )
    return {
        "schema_version": 1,
        "status": "reported",
        "gates": {
            "gate3": {
                "status": gate3.get("status") or "not-run",
                "source": "live-proof.json#/gate3/status",
            },
            "gate4": {
                "status": gate4.get("status") or "not-run",
                "source": "live-proof.json#/gate4/status",
                "blockers": list(gate4.get("blockers") or []),
            },
            "gate5": {
                "status": (
                    gate5_diff.get("status") or "not-run"
                    if isinstance(gate5_diff, dict)
                    else "not-run"
                ),
                "source": (
                    "gate5-drift-diff.json#/status"
                    if isinstance(gate5_diff, dict)
                    else None
                ),
            },
        },
        "gate4_scale": scale,
        "gate5_failure_onset": {
            "earlier": sum(
                1 for row in onset
                if row.get("classification") == "failure-onset-earlier"
            ),
            "later": sum(
                1 for row in onset
                if row.get("classification") == "failure-onset-later"
            ),
            "stable": sum(
                1 for row in onset
                if row.get("classification") == "failure-onset-stable"
            ),
            "not_comparable": sum(
                1 for row in onset
                if row.get("classification") == "not-comparable"
            ),
        },
        "provenance": {
            "live_proof": "live-proof.json",
            "gate5_diff": (
                "gate5-drift-diff.json"
                if isinstance(gate5_diff, dict)
                else "missing"
            ),
            "policy": "read-only-summary-no-rejudging",
        },
    }
