from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def _fingerprint(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("lineage_fingerprint", None)
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_lineage(
    decision: dict[str, Any],
    *,
    prior_lineage: dict[str, Any] | None = None,
    expected_reference_run_id: str | None = None,
    expected_candidate_run_id: str | None = None,
    candidate_git_sha: str | None = None,
) -> dict[str, Any]:
    if decision.get("schema_version") != 1:
        raise ValueError(f"unsupported promotion decision schema: {decision.get('schema_version')!r}")
    policy = decision.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("promotion decision policy is missing or invalid")
    required_policy = {"max_cost_ratio", "max_latency_ratio", "max_scale20_recall_drop", "requires_gate5_pass", "requires_scale20_comparability"}
    missing_policy = sorted(required_policy - set(policy))
    if missing_policy:
        raise ValueError("promotion decision policy is incomplete: " + ",".join(missing_policy))
    if policy.get("requires_gate5_pass") is not True:
        raise ValueError("promotion decision must require Gate 5 PASS")
    if policy.get("requires_scale20_comparability") is not True:
        raise ValueError("promotion decision must require 20x comparability")
    limits = {"max_cost_ratio": 1.25, "max_latency_ratio": 1.25, "max_scale20_recall_drop": 0.05}
    for key, allowed in limits.items():
        value = policy.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"promotion policy {key} must be numeric")
        if float(value) > allowed:
            raise ValueError(f"promotion policy {key}={float(value):.3f} exceeds allowed {allowed:.3f}")

    reference = decision.get("reference_run_id")
    candidate = decision.get("candidate_run_id")
    outcome = str(decision.get("decision") or "").upper()

    if outcome not in {"PROMOTE", "HOLD", "REJECT"}:
        raise ValueError(f"invalid promotion decision: {outcome!r}")
    if not reference or not candidate:
        raise ValueError("promotion decision must identify both reference and candidate runs")
    if reference == candidate:
        raise ValueError("reference and candidate run IDs must differ")
    if expected_reference_run_id and str(reference) != str(expected_reference_run_id):
        raise ValueError(
            f"reference run mismatch: decision={reference}, expected={expected_reference_run_id}"
        )
    if expected_candidate_run_id and str(candidate) != str(expected_candidate_run_id):
        raise ValueError(
            f"candidate run mismatch: decision={candidate}, expected={expected_candidate_run_id}"
        )

    if prior_lineage:
        events = list(prior_lineage.get("events") or [])
        root = prior_lineage.get("root_reference_run_id")
        current = prior_lineage.get("current_reference_run_id")
        if not root or not current:
            raise ValueError("prior lineage is missing root/current reference identity")
        prior_fp = prior_lineage.get("lineage_fingerprint")
        if prior_fp and prior_fp != _fingerprint(prior_lineage):
            raise ValueError("prior lineage fingerprint mismatch")
        if str(current) != str(reference):
            raise ValueError(
                f"lineage fork rejected: current reference={current}, decision reference={reference}"
            )
    else:
        events = []
        root = reference
        current = reference

    event = {
        "sequence": len(events) + 1,
        "reference_run_id": reference,
        "candidate_run_id": candidate,
        "decision": outcome,
        "candidate_git_sha": candidate_git_sha,
        "hard_failures": list(decision.get("hard_failures") or []),
        "warnings": list(decision.get("warnings") or []),
        "policy": dict(decision.get("policy") or {}),
    }
    events.append(event)

    if outcome == "PROMOTE":
        current = candidate

    payload = {
        "schema_version": max(2, int(prior_lineage.get("schema_version") or 1)) if prior_lineage else 2,
        "root_reference_run_id": root,
        "current_reference_run_id": current,
        "event_count": len(events),
        "events": events,
        "rollback_count": int((prior_lineage or {}).get("rollback_count") or 0),
    }
    if prior_lineage and prior_lineage.get("supersedes_lineage_fingerprint"):
        payload["supersedes_lineage_fingerprint"] = prior_lineage["supersedes_lineage_fingerprint"]
    payload["lineage_fingerprint"] = _fingerprint(payload)
    return payload


def render_markdown(lineage: dict[str, Any]) -> str:
    lines = [
        "# Promotion Lineage",
        "",
        f"Root reference: `{lineage.get('root_reference_run_id')}`",
        f"Current reference: `{lineage.get('current_reference_run_id')}`",
        f"Events: {lineage.get('event_count')}",
        f"Fingerprint: `{lineage.get('lineage_fingerprint')}`",
        "",
        "| # | Reference | Candidate | Decision | Candidate SHA |",
        "|---:|:---|:---|:---|:---|",
    ]
    for event in lineage.get("events") or []:
        lines.append(
            f"| {event.get('sequence')} | {event.get('reference_run_id')} | "
            f"{event.get('candidate_run_id')} | {event.get('decision')} | "
            f"{event.get('candidate_git_sha') or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Append one verified promotion event to a proof lineage.")
    ap.add_argument("--decision", type=Path, required=True)
    ap.add_argument("--prior-lineage", type=Path)
    ap.add_argument("--expected-reference-run-id")
    ap.add_argument("--expected-candidate-run-id")
    ap.add_argument("--candidate-git-sha")
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args = ap.parse_args()

    decision = _load(args.decision)
    if not decision:
        raise SystemExit("promotion decision artifact is missing or invalid")
    lineage = build_lineage(
        decision,
        prior_lineage=_load(args.prior_lineage),
        expected_reference_run_id=args.expected_reference_run_id,
        expected_candidate_run_id=args.expected_candidate_run_id,
        candidate_git_sha=args.candidate_git_sha,
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(lineage) + "\n", encoding="utf-8")
    print(args.markdown.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
