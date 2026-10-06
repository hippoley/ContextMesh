from __future__ import annotations

from typing import Any


def evidence_check(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {
            "schema_version": 1,
            "decision": "hold",
            "reasons": ["evidence-summary-missing"],
        }
    reasons: list[str] = []
    gates = summary.get("gates") or {}
    for gate_name in ("gate3", "gate4"):
        gate = gates.get(gate_name) or {}
        status = str(gate.get("status") or "not-run").lower()
        if status != "pass":
            reasons.append(f"{gate_name}:{status}")
        for blocker in gate.get("blockers") or []:
            reasons.append(f"{gate_name}-blocker:{blocker}")

    gate5 = gates.get("gate5") or {}
    gate5_status = str(gate5.get("status") or "not-run").lower()
    if gate5_status not in {"pass", "not-run"}:
        reasons.append(f"gate5:{gate5_status}")

    onset = summary.get("gate5_failure_onset") or {}
    earlier = int(onset.get("earlier") or 0)
    if earlier:
        reasons.append(f"failure-onset-earlier:{earlier}")

    return {
        "schema_version": 1,
        "decision": "pass" if not reasons else "hold",
        "reasons": reasons,
        "source_schema_version": summary.get("schema_version"),
        "policy": "evidence-readiness-only-not-promotion",
    }
