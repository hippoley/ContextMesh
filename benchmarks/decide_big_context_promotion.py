from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def _metric(diff: dict[str, Any], section: str, key: str, field: str) -> float | None:
    item = (diff.get(section) or {}).get(key) or {}
    value = item.get(field)
    return None if value is None else float(value)


def decide(
    diff: dict[str, Any] | None,
    *,
    max_cost_ratio: float = 1.25,
    max_latency_ratio: float = 1.25,
    max_scale20_recall_drop: float = 0.05,
) -> dict[str, Any]:
    approved_limits = {
        "max_cost_ratio": 1.25,
        "max_latency_ratio": 1.25,
        "max_scale20_recall_drop": 0.05,
    }
    requested_limits = {
        "max_cost_ratio": max_cost_ratio,
        "max_latency_ratio": max_latency_ratio,
        "max_scale20_recall_drop": max_scale20_recall_drop,
    }
    for key, approved in approved_limits.items():
        value = requested_limits[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"promotion policy {key} must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError(f"promotion policy {key} must be finite")
        if value < 0:
            raise ValueError(f"promotion policy {key} must be non-negative")
        if float(value) > approved:
            raise ValueError(f"promotion policy {key}={float(value):.3f} exceeds approved {approved:.3f}")
    if not diff or diff.get("status") in {"not-comparable", "not-run", None}:
        return {
            "schema_version": 1,
            "decision": "HOLD",
            "reasons": ["candidate is not comparable against a completed reference run"],
            "hard_failures": [],
            "warnings": [],
        }

    hard_failures: list[str] = []
    warnings: list[str] = []

    if str(diff.get("status")).lower() != "pass":
        hard_failures.append(f"gate5-status={diff.get('status')}")

    scale20_delta = _metric(diff, "scale_20x", "contextmesh_evidence_recall", "delta")
    if scale20_delta is None:
        hard_failures.append("scale20-contextmesh-recall-missing")
    elif scale20_delta < -max_scale20_recall_drop:
        hard_failures.append(
            f"scale20-contextmesh-recall-drop={-scale20_delta:.3f}>"
            f"{max_scale20_recall_drop:.3f}"
        )

    cost_ratio = _metric(diff, "operations", "estimated_cost_usd", "ratio")
    latency_ratio = _metric(diff, "operations", "latency_seconds", "ratio")

    if cost_ratio is None:
        warnings.append("cost-ratio-unavailable")
    elif cost_ratio > max_cost_ratio:
        hard_failures.append(f"cost-ratio={cost_ratio:.3f}>{max_cost_ratio:.3f}")

    if latency_ratio is None:
        warnings.append("latency-ratio-unavailable")
    elif latency_ratio > max_latency_ratio:
        hard_failures.append(
            f"latency-ratio={latency_ratio:.3f}>{max_latency_ratio:.3f}"
        )

    blockers = list(diff.get("blockers") or [])
    if blockers:
        hard_failures.extend(f"gate5:{item}" for item in blockers)

    if hard_failures:
        decision = "REJECT"
    elif warnings:
        decision = "HOLD"
    else:
        decision = "PROMOTE"

    return {
        "schema_version": 1,
        "decision": decision,
        "reference_run_id": diff.get("reference_run_id"),
        "candidate_run_id": diff.get("candidate_run_id"),
        "hard_failures": hard_failures,
        "warnings": warnings,
        "reasons": hard_failures or warnings or ["all promotion constraints satisfied"],
        "policy": {
            "max_cost_ratio": max_cost_ratio,
            "max_latency_ratio": max_latency_ratio,
            "max_scale20_recall_drop": max_scale20_recall_drop,
            "requires_gate5_pass": True,
            "requires_scale20_comparability": True,
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Promotion Decision",
        "",
        f"Decision: **{result.get('decision')}**",
        "",
    ]
    if result.get("reference_run_id") is not None:
        lines.append(f"Reference run: `{result.get('reference_run_id')}`")
    if result.get("candidate_run_id") is not None:
        lines.append(f"Candidate run: `{result.get('candidate_run_id')}`")
    lines += ["", "## Reasons", ""]
    for reason in result.get("reasons") or []:
        lines.append(f"- {reason}")
    lines += ["", "## Policy", ""]
    for key, value in (result.get("policy") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Decide whether a candidate proof run should replace its reference.")
    ap.add_argument("--drift-diff", type=Path, required=True)
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    ap.add_argument("--max-cost-ratio", type=float, default=1.25)
    ap.add_argument("--max-latency-ratio", type=float, default=1.25)
    ap.add_argument("--max-scale20-recall-drop", type=float, default=0.05)
    args = ap.parse_args()

    result = decide(
        _load(args.drift_diff),
        max_cost_ratio=args.max_cost_ratio,
        max_latency_ratio=args.max_latency_ratio,
        max_scale20_recall_drop=args.max_scale20_recall_drop,
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(result) + "\n", encoding="utf-8")
    print(args.markdown.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
