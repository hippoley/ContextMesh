from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def build_manifest(
    result_dir: Path,
    *,
    run_id: str,
    git_sha: str,
    provider: str,
    model: str,
    context_tokens: int,
    workers: int,
    smoke_only: bool,
    run_scale: bool,
    reference_run_id: str = "",
) -> dict[str, Any]:
    cost = _load(result_dir / "cost-estimate.json")
    smoke = _load(result_dir / "provider-smoke.json")
    proof = _load(result_dir / "live-proof.json")
    verification = _load(result_dir / "frozen-proof-verification.json")
    scale_plan = _load(result_dir / "gate4-scale-plan.json")
    promotion = _load(result_dir / "promotion-decision.json")
    lineage = _load(result_dir / "promotion-lineage.json")
    provider_blocker = _load(result_dir / "provider-blocker.json")

    if provider_blocker is not None:
        stage = "provider-configuration-blocked"
    elif proof is not None:
        stage = "live-proof-complete"
    elif smoke is not None:
        stage = "provider-smoke-complete"
    elif cost is not None:
        stage = "preflight-complete-no-provider"
    elif verification is not None:
        stage = "frozen-proof-verified"
    else:
        stage = "setup-incomplete"

    gate_statuses: dict[str, str | None] = {}
    claim_proven = None
    if proof is not None:
        claim_proven = proof.get("claim_proven")
        for key in ("gate1", "gate2", "gate3", "gate4", "gate5"):
            value = proof.get(key)
            if isinstance(value, dict):
                gate_statuses[key] = value.get("status")
            else:
                gate_statuses[key] = None

    return {
        "schema_version": 1,
        "run_id": run_id,
        "git_sha": git_sha,
        "provider": provider,
        "model": model,
        "context_tokens": context_tokens,
        "workers": workers,
        "smoke_only": smoke_only,
        "run_scale": run_scale,
        "reference_run_id": reference_run_id or None,
        "stage": stage,
        "claim_proven": claim_proven,
        "gate_statuses": gate_statuses,
        "provider_calls": int(smoke.get("provider_calls") or 0) if smoke else 0,
        "provider_blocker": provider_blocker,
        "provider_tokens": int(smoke.get("total_tokens") or 0) if smoke else 0,
        "estimated_cost_cny": cost.get("estimated_cost_cny") if cost else None,
        "within_budget": cost.get("within_budget") if cost else None,
        "frozen_proof_verified": bool(verification),
        "scale_plan_fingerprint": (
            scale_plan.get("anchor_fingerprint") if scale_plan else None
        ),
        "promotion_decision": promotion.get("decision") if promotion else None,
        "promotion_lineage_fingerprint": (
            lineage.get("lineage_fingerprint") if lineage else None
        ),
        "current_reference_run_id": (
            lineage.get("current_reference_run_id") if lineage else None
        ),
        "files_present": sorted(path.name for path in result_dir.iterdir() if path.is_file()),
        "credential_material_recorded": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Create a self-describing manifest for a Big Context live workflow artifact."
    )
    ap.add_argument("--result-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--git-sha", required=True)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--context-tokens", type=int, required=True)
    ap.add_argument("--workers", type=int, required=True)
    ap.add_argument("--smoke-only", choices=["true", "false"], required=True)
    ap.add_argument("--run-scale", choices=["true", "false"], required=True)
    ap.add_argument("--reference-run-id", default="")
    args = ap.parse_args()

    payload = build_manifest(
        args.result_dir,
        run_id=args.run_id,
        git_sha=args.git_sha,
        provider=args.provider,
        model=args.model,
        context_tokens=args.context_tokens,
        workers=args.workers,
        smoke_only=args.smoke_only == "true",
        run_scale=args.run_scale == "true",
        reference_run_id=args.reference_run_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
