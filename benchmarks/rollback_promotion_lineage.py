from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("lineage must be a JSON object")
    return raw


def _fingerprint(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("lineage_fingerprint", None)
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _promoted_nodes(lineage: dict[str, Any]) -> set[str]:
    nodes = {str(lineage.get("root_reference_run_id") or "")}
    for event in lineage.get("events") or []:
        if isinstance(event, dict) and str(event.get("decision") or "").upper() == "PROMOTE":
            candidate = event.get("candidate_run_id")
            if candidate:
                nodes.add(str(candidate))
    nodes.discard("")
    return nodes


def rollback(
    lineage: dict[str, Any],
    *,
    target_run_id: str,
    reason: str,
    incident_ref: str | None = None,
    operator: str | None = None,
) -> dict[str, Any]:
    prior_fp = lineage.get("lineage_fingerprint")
    if not prior_fp or prior_fp != _fingerprint(lineage):
        raise ValueError("lineage fingerprint mismatch")

    current = str(lineage.get("current_reference_run_id") or "")
    target = str(target_run_id or "")
    if not current:
        raise ValueError("lineage current reference is missing")
    if not target:
        raise ValueError("rollback target is required")
    if target == current:
        raise ValueError("rollback target is already the current reference")
    if not reason.strip():
        raise ValueError("rollback reason is required")

    eligible = _promoted_nodes(lineage)
    if target not in eligible:
        raise ValueError(
            f"rollback target {target!r} is not a previously promoted reference"
        )

    events = list(lineage.get("events") or [])
    event = {
        "sequence": len(events) + 1,
        "event_type": "ROLLBACK",
        "from_reference_run_id": current,
        "to_reference_run_id": target,
        "reason": reason.strip(),
        "incident_ref": incident_ref or None,
        "operator": operator or None,
    }
    events.append(event)

    payload = {
        "schema_version": 2,
        "root_reference_run_id": lineage.get("root_reference_run_id"),
        "current_reference_run_id": target,
        "event_count": len(events),
        "events": events,
        "rollback_count": int(lineage.get("rollback_count") or 0) + 1,
        "supersedes_lineage_fingerprint": prior_fp,
    }
    payload["lineage_fingerprint"] = _fingerprint(payload)
    return payload


def render_markdown(lineage: dict[str, Any]) -> str:
    last = (lineage.get("events") or [])[-1]
    lines = [
        "# Proof Reference Rollback",
        "",
        "> This changes the benchmark/reference lineage only. It does not claim that production traffic was redeployed.",
        "",
        f"Current reference: `{lineage.get('current_reference_run_id')}`",
        f"Rollback count: {lineage.get('rollback_count', 0)}",
        f"Fingerprint: `{lineage.get('lineage_fingerprint')}`",
        "",
        "## Latest rollback",
        "",
        f"- From: `{last.get('from_reference_run_id')}`",
        f"- To: `{last.get('to_reference_run_id')}`",
        f"- Reason: {last.get('reason')}",
    ]
    if last.get("incident_ref"):
        lines.append(f"- Incident: {last.get('incident_ref')}")
    if last.get("operator"):
        lines.append(f"- Operator: {last.get('operator')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Rollback the proof reference to a previously promoted ancestor.")
    ap.add_argument("--lineage", type=Path, required=True)
    ap.add_argument("--target-run-id", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--incident-ref", default="")
    ap.add_argument("--operator", default="")
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args = ap.parse_args()

    result = rollback(
        _load(args.lineage),
        target_run_id=args.target_run_id,
        reason=args.reason,
        incident_ref=args.incident_ref or None,
        operator=args.operator or None,
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(result) + "\n", encoding="utf-8")
    print(args.markdown.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
