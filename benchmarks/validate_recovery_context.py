from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def _fingerprint(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("lineage_fingerprint", None)
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_recovery_context(
    lineage: dict[str, Any],
    *,
    reference_run_id: str,
    candidate_run_id: str,
) -> dict[str, Any]:
    fp = lineage.get("lineage_fingerprint")
    if not fp or fp != _fingerprint(lineage):
        raise ValueError("lineage fingerprint mismatch")

    current = str(lineage.get("current_reference_run_id") or "")
    if current != str(reference_run_id):
        raise ValueError(
            f"recovery reference mismatch: lineage current={current}, requested={reference_run_id}"
        )
    if str(candidate_run_id) == current:
        raise ValueError("recovery candidate must differ from the current reference")

    events = list(lineage.get("events") or [])
    rollback_events = [
        event for event in events
        if isinstance(event, dict) and event.get("event_type") == "ROLLBACK"
    ]
    latest_rollback = rollback_events[-1] if rollback_events else None

    return {
        "schema_version": 1,
        "status": "revalidation-required" if latest_rollback else "normal-candidate",
        "reference_run_id": reference_run_id,
        "candidate_run_id": candidate_run_id,
        "lineage_fingerprint": fp,
        "rollback_count": int(lineage.get("rollback_count") or len(rollback_events)),
        "latest_rollback": latest_rollback,
        "requirements": {
            "fresh_gate3": True,
            "fresh_gate4": True,
            "fresh_gate5_against_current_reference": True,
            "fresh_promotion_decision": True,
            "prior_promotion_does_not_grant_recovery": True,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate whether a candidate is entering a post-rollback recovery/revalidation path.")
    ap.add_argument("--lineage", type=Path, required=True)
    ap.add_argument("--reference-run-id", required=True)
    ap.add_argument("--candidate-run-id", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    result = validate_recovery_context(
        _load(args.lineage),
        reference_run_id=args.reference_run_id,
        candidate_run_id=args.candidate_run_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
