from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class FrozenProofMismatch(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise FrozenProofMismatch(f"{path} must contain a JSON object")
    return obj


def verify_frozen_public_proof(
    *,
    download_manifest: dict[str, Any],
    gate4_plan: dict[str, Any],
    gate12_proof: dict[str, Any],
    gate4_preflight: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []

    current_sources = {
        str(item.get("name")): str(item.get("sha256"))
        for item in download_manifest.get("sources", [])
    }
    frozen_sources = {
        str(item.get("name")): str(item.get("sha256"))
        for item in gate12_proof.get("sources", [])
    }
    if current_sources != frozen_sources:
        missing = sorted(set(frozen_sources) - set(current_sources))
        extra = sorted(set(current_sources) - set(frozen_sources))
        changed = sorted(
            name
            for name in set(current_sources) & set(frozen_sources)
            if current_sources[name] != frozen_sources[name]
        )
        errors.append(
            "source-sha-set-mismatch:"
            f"missing={missing},extra={extra},changed={changed}"
        )

    expected_context = int(gate4_preflight["corpus"]["model_context_tokens"])
    actual_context = int(gate4_plan.get("model_context_tokens") or 0)
    if actual_context != expected_context:
        errors.append(
            f"context-window-mismatch:expected={expected_context},actual={actual_context}"
        )

    frozen_panel = gate4_preflight["panel"]
    expected_cases = list(frozen_panel["selected_case_ids"])
    actual_cases = list(gate4_plan.get("selected_case_ids") or [])
    if actual_cases != expected_cases:
        errors.append(
            "selected-case-order-mismatch:"
            f"expected={expected_cases},actual={actual_cases}"
        )

    expected_anchor = str(frozen_panel["anchor_fingerprint"])
    actual_anchor = str(gate4_plan.get("anchor_fingerprint") or "")
    if actual_anchor != expected_anchor:
        errors.append(
            "anchor-fingerprint-mismatch:"
            f"expected={expected_anchor},actual={actual_anchor}"
        )

    expected_points = {
        float(item["requested_ratio"]): item
        for item in gate4_preflight.get("points", [])
    }
    actual_points = {
        float(item["requested_ratio"]): item
        for item in gate4_plan.get("points", [])
    }
    if set(actual_points) != set(expected_points):
        errors.append(
            "scale-ratio-set-mismatch:"
            f"expected={sorted(expected_points)},actual={sorted(actual_points)}"
        )

    point_checks: list[dict[str, Any]] = []
    for ratio in sorted(set(expected_points) & set(actual_points)):
        expected = expected_points[ratio]
        actual = actual_points[ratio]
        check = {
            "requested_ratio": ratio,
            "projection_fingerprint": actual.get("projection_fingerprint"),
            "selected_blocks": actual.get("selected_blocks"),
            "estimated_tokens": actual.get("estimated_tokens"),
            "matches": True,
        }
        for field in (
            "projection_fingerprint",
            "selected_blocks",
            "selected_assets",
            "estimated_tokens",
        ):
            if actual.get(field) != expected.get(field):
                errors.append(
                    f"{ratio:g}x-{field}-mismatch:"
                    f"expected={expected.get(field)},actual={actual.get(field)}"
                )
                check["matches"] = False
        if abs(
            float(actual.get("actual_ratio") or 0.0)
            - float(expected.get("actual_ratio") or 0.0)
        ) > 1e-12:
            errors.append(
                f"{ratio:g}x-actual-ratio-mismatch:"
                f"expected={expected.get('actual_ratio')},"
                f"actual={actual.get('actual_ratio')}"
            )
            check["matches"] = False
        point_checks.append(check)

    if gate4_plan.get("ready_for_live_gate4") is not True:
        errors.append("current-gate4-plan-not-ready")

    report = {
        "schema_version": 1,
        "verified": not errors,
        "source_files": len(current_sources),
        "source_hashes_match": current_sources == frozen_sources,
        "context_tokens": actual_context,
        "selected_case_ids": actual_cases,
        "anchor_fingerprint": actual_anchor,
        "point_checks": point_checks,
        "errors": errors,
        "provider_calls_made": 0,
    }
    if errors:
        raise FrozenProofMismatch("; ".join(errors))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify a rebuilt public corpus/scale plan against committed frozen proof."
    )
    ap.add_argument("--download-manifest", type=Path, required=True)
    ap.add_argument("--gate4-plan", type=Path, required=True)
    ap.add_argument("--gate1-2-proof", type=Path, required=True)
    ap.add_argument("--gate4-preflight", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    try:
        report = verify_frozen_public_proof(
            download_manifest=_load(args.download_manifest),
            gate4_plan=_load(args.gate4_plan),
            gate12_proof=_load(args.gate1_2_proof),
            gate4_preflight=_load(args.gate4_preflight),
        )
    except FrozenProofMismatch as exc:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "verified": False,
                    "error": str(exc),
                    "provider_calls_made": 0,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"FROZEN_PUBLIC_PROOF_MISMATCH {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print("FROZEN_PUBLIC_PROOF_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
