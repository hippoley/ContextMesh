from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("live proof must be a JSON object")
    return raw


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


def write_curve_artifacts(proof_path: Path, csv_path: Path, md_path: Path) -> None:
    proof = _load(proof_path)
    rows = curve_rows(proof)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "requested_ratio",
        "actual_ratio",
        "status",
        "selected_blocks",
        "selected_assets",
        "estimated_tokens",
        "contextmesh_evidence_recall",
        "lexical_top_5_evidence_recall",
        "lexical_top_20_evidence_recall",
        "evidence_term_fidelity",
        "negative_accuracy",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    md_path.write_text(render_markdown(proof, rows) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Render Gate 4 scale results as stable CSV and Markdown artifacts.")
    ap.add_argument("--proof", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args = ap.parse_args()
    write_curve_artifacts(args.proof, args.csv, args.markdown)
    print(args.markdown.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
