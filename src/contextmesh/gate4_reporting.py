from __future__ import annotations

from typing import Any

def curve_rows(proof: dict[str, Any]) -> list[dict[str, Any]]:
    gate4 = proof.get("gate4")
    if not isinstance(gate4, dict):
        return []
    points = gate4.get("points") or []
    rows: list[dict[str, Any]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        baseline = point.get("baseline_evidence_recall") or {}
        rows.append({
            "requested_ratio": point.get("requested_ratio"),
            "actual_ratio": point.get("actual_ratio"),
            "status": point.get("status"),
            "selected_blocks": point.get("selected_blocks"),
            "selected_assets": point.get("selected_assets"),
            "estimated_tokens": point.get("estimated_tokens"),
            "contextmesh_evidence_recall": point.get("evidence_recall"),
            "lexical_top_5_evidence_recall": baseline.get("lexical-top-5"),
            "lexical_top_20_evidence_recall": baseline.get("lexical-top-20"),
            "evidence_term_fidelity": point.get("evidence_term_fidelity"),
            "negative_accuracy": point.get("negative_accuracy"),
        })
    return rows


def case_rows(proof: dict[str, Any]) -> list[dict[str, Any]]:
    gate4 = proof.get("gate4")
    if not isinstance(gate4, dict):
        return []
    out: list[dict[str, Any]] = []
    for point in gate4.get("points") or []:
        if not isinstance(point, dict):
            continue
        ratio = point.get("requested_ratio")
        for case in point.get("case_results") or []:
            if not isinstance(case, dict) or not case.get("expected_present", True):
                continue
            out.append({
                "requested_ratio": ratio,
                "case_id": case.get("case_id"),
                "kind": case.get("kind"),
                "recovered": case.get("recovered"),
                "term_recall": case.get("term_recall"),
                "coverage": case.get("coverage"),
                "visited_blocks": case.get("visited_blocks"),
                "total_blocks": case.get("total_blocks"),
                "judgment_valid": case.get("judgment_valid"),
                "latency_seconds": case.get("latency_seconds"),
            })
    return out


def render_markdown(proof: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    gate4 = proof.get("gate4")
    if not isinstance(gate4, dict):
        return "# Gate 4 Scale Curve\n\nStatus: **NOT RUN**\n"
    status = str(gate4.get("status") or "unknown").upper()
    lines = [
        "# Gate 4 Scale Curve",
        "",
        f"Status: **{status}**",
        "",
        "| Requested | Actual | ContextMesh recall | Lexical@5 recall | Lexical@20 recall | Blocks | Status |",
        "|---:|---:|---:|---:|---:|---:|:---|",
    ]
    def fmt(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)
    for row in rows:
        lines.append(
            "| "
            + " | ".join([
                fmt(row["requested_ratio"]),
                fmt(row["actual_ratio"]),
                fmt(row["contextmesh_evidence_recall"]),
                fmt(row["lexical_top_5_evidence_recall"]),
                fmt(row["lexical_top_20_evidence_recall"]),
                fmt(row["selected_blocks"]),
                fmt(row["status"]),
            ])
            + " |"
        )
    lines.extend([
        "",
        f"Max completed ratio: {fmt(gate4.get('max_completed_ratio'))}",
        "",
        f"ContextMesh recall drop: {fmt(gate4.get('recall_drop'))}",
        "",
    ])
    cases = case_rows(proof)
    if cases:
        lines.extend([
            "## Live case telemetry",
            "",
            "| Scale | Case | Kind | Recovered | Term recall | Coverage | Visited / total | Valid | Latency s |",
            "|---:|:---|:---|:---:|---:|---:|:---:|:---:|---:|",
        ])
        for case in cases:
            lines.append(
                "| " + " | ".join([
                    fmt(case["requested_ratio"]),
                    fmt(case["case_id"]),
                    fmt(case["kind"]),
                    fmt(case["recovered"]),
                    fmt(case["term_recall"]),
                    fmt(case["coverage"]),
                    f'{fmt(case["visited_blocks"])} / {fmt(case["total_blocks"])}',
                    fmt(case["judgment_valid"]),
                    fmt(case["latency_seconds"]),
                ]) + " |"
            )
        lines.append("")
    blockers = gate4.get("blockers") or []
    if blockers:
        lines.append("Blockers:")
        lines.extend(f"- {item}" for item in blockers)
        lines.append("")
    return "\n".join(lines)


