from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from contextmesh.gate5_reporting import case_drift_rows, scale_case_drift_matrix


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def _gate4_point(proof: dict[str, Any] | None, requested_ratio: float) -> dict[str, Any] | None:
    if not proof:
        return None
    gate4 = proof.get("gate4")
    if not isinstance(gate4, dict):
        return None
    best = None
    for point in gate4.get("points") or []:
        if not isinstance(point, dict):
            continue
        try:
            ratio = float(point.get("requested_ratio"))
        except (TypeError, ValueError):
            continue
        if abs(ratio - requested_ratio) < 1e-9:
            best = point
            break
    return best


def _delta(candidate: Any, reference: Any) -> float | None:
    if candidate is None or reference is None:
        return None
    return float(candidate) - float(reference)


def _ratio(candidate: Any, reference: Any) -> float | None:
    if candidate is None or reference in (None, 0, 0.0):
        return None
    return float(candidate) / float(reference)


def build_diff(
    reference_proof: dict[str, Any] | None,
    candidate_proof: dict[str, Any] | None,
) -> dict[str, Any]:
    if not reference_proof or not candidate_proof:
        return {
            "schema_version": 1,
            "status": "not-comparable",
            "reason": "reference or candidate live-proof.json is missing",
        }

    ref_snapshot = reference_proof.get("snapshot") or {}
    cand_snapshot = candidate_proof.get("snapshot") or {}
    cand_gate5 = candidate_proof.get("gate5") or {}
    gate5_delta = None
    if isinstance(cand_gate5, dict):
        deltas = cand_gate5.get("deltas") or []
        if deltas and isinstance(deltas[0], dict):
            gate5_delta = deltas[0]

    ref20 = _gate4_point(reference_proof, 20.0)
    cand20 = _gate4_point(candidate_proof, 20.0)

    def g(obj: dict[str, Any], key: str) -> Any:
        return obj.get(key) if isinstance(obj, dict) else None

    out = {
        "schema_version": 1,
        "status": g(cand_gate5, "status") or "not-run",
        "reference_run_id": g(ref_snapshot, "run_id") or reference_proof.get("run_id"),
        "candidate_run_id": g(cand_snapshot, "run_id") or candidate_proof.get("run_id"),
        "reference_config_fingerprint": (
            g(cand_gate5.get("reference") or {}, "config_fingerprint")
            if isinstance(cand_gate5, dict)
            else None
        ),
        "candidate_config_fingerprint": g(gate5_delta or {}, "config_fingerprint"),
        "quality": {
            "evidence_recall": {
                "reference": g(ref_snapshot, "evidence_recall"),
                "candidate": g(cand_snapshot, "evidence_recall"),
                "delta": _delta(g(cand_snapshot, "evidence_recall"), g(ref_snapshot, "evidence_recall")),
            },
            "task_accuracy": {
                "reference": g(ref_snapshot, "task_accuracy"),
                "candidate": g(cand_snapshot, "task_accuracy"),
                "delta": _delta(g(cand_snapshot, "task_accuracy"), g(ref_snapshot, "task_accuracy")),
            },
            "authority_accuracy": {
                "reference": g(ref_snapshot, "authority_accuracy"),
                "candidate": g(cand_snapshot, "authority_accuracy"),
                "delta": _delta(g(cand_snapshot, "authority_accuracy"), g(ref_snapshot, "authority_accuracy")),
            },
            "negative_accuracy": {
                "reference": g(ref_snapshot, "negative_accuracy"),
                "candidate": g(cand_snapshot, "negative_accuracy"),
                "delta": _delta(g(cand_snapshot, "negative_accuracy"), g(ref_snapshot, "negative_accuracy")),
            },
        },
        "operations": {
            "estimated_cost_usd": {
                "reference": g(ref_snapshot, "estimated_cost_usd"),
                "candidate": g(cand_snapshot, "estimated_cost_usd"),
                "ratio": _ratio(g(cand_snapshot, "estimated_cost_usd"), g(ref_snapshot, "estimated_cost_usd")),
            },
            "latency_seconds": {
                "reference": g(ref_snapshot, "latency_seconds"),
                "candidate": g(cand_snapshot, "latency_seconds"),
                "ratio": _ratio(g(cand_snapshot, "latency_seconds"), g(ref_snapshot, "latency_seconds")),
            },
        },
        "scale_20x": {
            "contextmesh_evidence_recall": {
                "reference": g(ref20 or {}, "evidence_recall"),
                "candidate": g(cand20 or {}, "evidence_recall"),
                "delta": _delta(g(cand20 or {}, "evidence_recall"), g(ref20 or {}, "evidence_recall")),
            },
            "lexical_top_5_evidence_recall": {
                "reference": g(g(ref20 or {}, "baseline_evidence_recall") or {}, "lexical-top-5"),
                "candidate": g(g(cand20 or {}, "baseline_evidence_recall") or {}, "lexical-top-5"),
                "delta": _delta(
                    g(g(cand20 or {}, "baseline_evidence_recall") or {}, "lexical-top-5"),
                    g(g(ref20 or {}, "baseline_evidence_recall") or {}, "lexical-top-5"),
                ),
            },
            "lexical_top_20_evidence_recall": {
                "reference": g(g(ref20 or {}, "baseline_evidence_recall") or {}, "lexical-top-20"),
                "candidate": g(g(cand20 or {}, "baseline_evidence_recall") or {}, "lexical-top-20"),
                "delta": _delta(
                    g(g(cand20 or {}, "baseline_evidence_recall") or {}, "lexical-top-20"),
                    g(g(ref20 or {}, "baseline_evidence_recall") or {}, "lexical-top-20"),
                ),
            },
        },
        "case_drift_20x": case_drift_rows(ref20, cand20),
        "scale_case_drift": scale_case_drift_matrix(reference_proof, candidate_proof),
        "blockers": list(g(cand_gate5, "blockers") or []),
    }
    return out


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(diff: dict[str, Any]) -> str:
    if diff.get("status") == "not-comparable":
        return "# Gate 5 Drift Diff\n\nStatus: **NOT COMPARABLE**\n\n" + str(diff.get("reason") or "") + "\n"
    lines = [
        "# Gate 5 Drift Diff",
        "",
        f"Status: **{str(diff.get('status') or 'unknown').upper()}**",
        "",
        f"Reference run: `{diff.get('reference_run_id')}`",
        f"Candidate run: `{diff.get('candidate_run_id')}`",
        "",
        "## Quality",
        "",
        "| Metric | Reference | Candidate | Delta |",
        "|:---|---:|---:|---:|",
    ]
    for key, label in [
        ("evidence_recall", "Evidence recall"),
        ("task_accuracy", "Task accuracy"),
        ("authority_accuracy", "Authority accuracy"),
        ("negative_accuracy", "Negative accuracy"),
    ]:
        item = diff["quality"][key]
        lines.append(f"| {label} | {_fmt(item['reference'])} | {_fmt(item['candidate'])} | {_fmt(item['delta'])} |")

    lines += [
        "",
        "## Operations",
        "",
        "| Metric | Reference | Candidate | Ratio |",
        "|:---|---:|---:|---:|",
    ]
    for key, label in [
        ("estimated_cost_usd", "Estimated cost (USD)"),
        ("latency_seconds", "Latency (s)"),
    ]:
        item = diff["operations"][key]
        lines.append(f"| {label} | {_fmt(item['reference'])} | {_fmt(item['candidate'])} | {_fmt(item['ratio'])} |")

    lines += [
        "",
        "## 20× Scale Point",
        "",
        "| Metric | Reference | Candidate | Delta |",
        "|:---|---:|---:|---:|",
    ]
    for key, label in [
        ("contextmesh_evidence_recall", "ContextMesh recall"),
        ("lexical_top_5_evidence_recall", "Lexical@5 recall"),
        ("lexical_top_20_evidence_recall", "Lexical@20 recall"),
    ]:
        item = diff["scale_20x"][key]
        lines.append(f"| {label} | {_fmt(item['reference'])} | {_fmt(item['candidate'])} | {_fmt(item['delta'])} |")

    case_drift = diff.get("case_drift_20x") or []
    if case_drift:
        lines += [
            "",
            "## 20× Case Drift",
            "",
            "| Case | Kind | Reference | Candidate | Classification |",
            "|:---|:---|:---:|:---:|:---|",
        ]
        for row in case_drift:
            lines.append(
                f"| {row.get('case_id')} | {row.get('kind')} | "
                f"{_fmt(row.get('reference_recovered'))} | "
                f"{_fmt(row.get('candidate_recovered'))} | "
                f"{row.get('classification')} |"
            )
    onset = (diff.get("scale_case_drift") or {}).get("failure_onset") or []
    if onset:
        lines += [
            "",
            "## Failure Onset",
            "",
            "| Case | Reference first fail | Candidate first fail | Classification |",
            "|:---|---:|---:|:---|",
        ]
        for row in onset:
            lines.append(
                f"| {row.get('case_id')} | "
                f"{_fmt(row.get('reference_first_failure_ratio'))} | "
                f"{_fmt(row.get('candidate_first_failure_ratio'))} | "
                f"{row.get('classification')} |"
            )
    blockers = diff.get("blockers") or []
    if blockers:
        lines += ["", "## Blockers", ""]
        lines.extend(f"- {item}" for item in blockers)
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render reference-vs-candidate Gate 5 drift artifacts.")
    ap.add_argument("--reference-proof", type=Path, required=True)
    ap.add_argument("--candidate-proof", type=Path, required=True)
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args = ap.parse_args()

    diff = build_diff(_load(args.reference_proof), _load(args.candidate_proof))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(diff, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(diff) + "\n", encoding="utf-8")
    print(args.markdown.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
