from __future__ import annotations

from typing import Any


def _case_map(point: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(point, dict):
        return {}
    return {
        str(row.get("case_id")): row
        for row in point.get("case_results") or []
        if isinstance(row, dict) and row.get("case_id") and row.get("expected_present", True)
    }


def case_drift_rows(
    reference_point: dict[str, Any] | None,
    candidate_point: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    reference = _case_map(reference_point)
    candidate = _case_map(candidate_point)
    rows: list[dict[str, Any]] = []
    for case_id in sorted(set(reference) | set(candidate)):
        ref = reference.get(case_id)
        cand = candidate.get(case_id)
        if ref is None or cand is None:
            classification = "not-comparable"
        elif bool(ref.get("recovered")) and not bool(cand.get("recovered")):
            classification = "recovered-to-lost"
        elif not bool(ref.get("recovered")) and bool(cand.get("recovered")):
            classification = "lost-to-recovered"
        elif bool(ref.get("recovered")) and bool(cand.get("recovered")):
            classification = "stable-recovered"
        else:
            classification = "stable-lost"
        rows.append({
            "case_id": case_id,
            "kind": (cand or ref or {}).get("kind"),
            "reference_recovered": None if ref is None else ref.get("recovered"),
            "candidate_recovered": None if cand is None else cand.get("recovered"),
            "reference_term_recall": None if ref is None else ref.get("term_recall"),
            "candidate_term_recall": None if cand is None else cand.get("term_recall"),
            "reference_coverage": None if ref is None else ref.get("coverage"),
            "candidate_coverage": None if cand is None else cand.get("coverage"),
            "classification": classification,
        })
    return rows
