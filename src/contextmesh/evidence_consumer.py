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
    source_schema_version = summary.get("schema_version")
    if source_schema_version != 1:
        reasons.append(f"unsupported-schema-version:{source_schema_version}")

    gates = summary.get("gates")
    if not isinstance(gates, dict):
        gates = {}
        reasons.append("invalid-gates")

    for gate_name in ("gate3", "gate4"):
        gate = gates.get(gate_name)
        if not isinstance(gate, dict):
            reasons.append(f"{gate_name}:invalid")
            continue
        status = str(gate.get("status") or "not-run").lower()
        if status != "pass":
            reasons.append(f"{gate_name}:{status}")
        blockers = gate.get("blockers") or []
        if not isinstance(blockers, list):
            reasons.append(f"{gate_name}-blockers:invalid")
        else:
            for blocker in blockers:
                reasons.append(f"{gate_name}-blocker:{blocker}")

    gate5 = gates.get("gate5")
    if gate5 is None:
        gate5 = {}
    if not isinstance(gate5, dict):
        reasons.append("gate5:invalid")
    else:
        gate5_status = str(gate5.get("status") or "not-run").lower()
        if gate5_status not in {"pass", "not-run"}:
            reasons.append(f"gate5:{gate5_status}")

    onset = summary.get("gate5_failure_onset") or {}
    if not isinstance(onset, dict):
        reasons.append("invalid-failure-onset")
    else:
        raw_earlier = onset.get("earlier", 0)
        if isinstance(raw_earlier, bool) or not isinstance(raw_earlier, int):
            reasons.append("invalid-failure-onset-count")
        elif raw_earlier < 0:
            reasons.append("invalid-failure-onset-count")
        elif raw_earlier:
            reasons.append(f"failure-onset-earlier:{raw_earlier}")

    return {
        "schema_version": 1,
        "decision": "pass" if not reasons else "hold",
        "reasons": reasons,
        "source_schema_version": source_schema_version,
        "policy": "evidence-readiness-only-not-promotion",
    }
