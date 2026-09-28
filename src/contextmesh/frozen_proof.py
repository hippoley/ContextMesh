from __future__ import annotations

import hashlib
import json

from typing import Any


class FrozenProofMismatch(RuntimeError):
    pass


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _ordered_sha256(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def verify_frozen_public_proof(
    *,
    download_manifest: dict[str, Any],
    gate4_plan: dict[str, Any],
    gate12_proof: dict[str, Any],
    gate4_preflight: dict[str, Any],
    corpus_manifest: dict[str, Any] | None = None,
    needle_matrix: dict[str, Any] | None = None,
    task_cases: dict[str, Any] | None = None,
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

    frozen_fingerprints = gate12_proof.get("frozen_fingerprints") or {}
    fingerprint_checks: dict[str, dict[str, Any]] = {}

    expected_coverage = frozen_fingerprints.get("coverage_fingerprint")
    if expected_coverage:
        if corpus_manifest is None:
            errors.append("coverage-fingerprint-input-missing")
        else:
            actual_coverage = _ordered_sha256(
                [str(x) for x in corpus_manifest.get("required_block_ids", [])]
            )
            matches = actual_coverage == str(expected_coverage)
            fingerprint_checks["coverage"] = {
                "expected": str(expected_coverage),
                "actual": actual_coverage,
                "matches": matches,
            }
            if not matches:
                errors.append(
                    "coverage-fingerprint-mismatch:"
                    f"expected={expected_coverage},actual={actual_coverage}"
                )

    expected_needles = frozen_fingerprints.get("needle_matrix_fingerprint")
    if expected_needles:
        if needle_matrix is None:
            errors.append("needle-matrix-fingerprint-input-missing")
        else:
            actual_needles = _canonical_sha256(needle_matrix.get("cases", []))
            matches = actual_needles == str(expected_needles)
            fingerprint_checks["needle_matrix"] = {
                "expected": str(expected_needles),
                "actual": actual_needles,
                "matches": matches,
            }
            if not matches:
                errors.append(
                    "needle-matrix-fingerprint-mismatch:"
                    f"expected={expected_needles},actual={actual_needles}"
                )

    expected_tasks = frozen_fingerprints.get("task_set_fingerprint")
    if expected_tasks:
        if task_cases is None:
            errors.append("task-set-fingerprint-input-missing")
        else:
            actual_tasks = _canonical_sha256(task_cases.get("cases", []))
            matches = actual_tasks == str(expected_tasks)
            fingerprint_checks["task_set"] = {
                "expected": str(expected_tasks),
                "actual": actual_tasks,
                "matches": matches,
            }
            if not matches:
                errors.append(
                    "task-set-fingerprint-mismatch:"
                    f"expected={expected_tasks},actual={actual_tasks}"
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
        "fingerprint_checks": fingerprint_checks,
        "errors": errors,
        "provider_calls_made": 0,
    }
    if errors:
        raise FrozenProofMismatch("; ".join(errors))
    return report
