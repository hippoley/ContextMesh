from __future__ import annotations

from pathlib import Path
from typing import Any

from contextmesh.big_context_proof import (
    NeedleCase,
    NeedleKind,
    _ground_truth_block_matches,
    _term_hits,
)
from contextmesh.reader import CorpusReader
from contextmesh.store import FileContextStore


def lexical_case_diagnostics(
    store: FileContextStore,
    corpus_id: str,
    cases: list[NeedleCase],
    top_k: int,
) -> list[dict[str, Any]]:
    """Explain retrieval-only evidence recovery without changing the scorer."""
    reader = CorpusReader(store, corpus_id)
    out: list[dict[str, Any]] = []
    for case in cases:
        if not case.expected_present:
            out.append({
                "case_id": case.id,
                "kind": case.kind.value,
                "expected_present": False,
                "recovered": None,
                "best_ground_truth_rank": None,
                "matched_terms": [],
                "matched_assets": [],
            })
            continue

        ordered = reader.lexical_order(case.question)
        selected_ids = ordered[: max(0, top_k)]
        matched_terms: set[str] = set()
        matched_assets: set[str] = set()
        matched_target = False
        best_rank: int | None = None

        for rank, block_id in enumerate(ordered, start=1):
            block = reader.read(block_id)
            if _ground_truth_block_matches(block, case):
                best_rank = rank
                break

        for block_id in selected_ids:
            block = reader.read(block_id)
            if not _ground_truth_block_matches(block, case):
                continue
            matched_target = True
            hits = _term_hits(block.text or "", case.match_terms)
            matched_terms.update(hits)
            if hits or not case.match_terms:
                matched_assets.add(Path(block.source.path).name)

        if case.match_terms:
            terms_ok = (
                len(matched_terms) == len(set(case.match_terms))
                if case.match_all_terms
                else bool(matched_terms)
            )
        else:
            terms_ok = matched_target

        required_asset_hits = case.required_asset_hits
        if required_asset_hits is None:
            required_asset_hits = (
                len(case.target_assets)
                if case.kind == NeedleKind.CROSS_FILE and case.target_assets
                else 1
            )
        assets_ok = len(matched_assets) >= required_asset_hits
        out.append({
            "case_id": case.id,
            "kind": case.kind.value,
            "modality": getattr(case, "modality", None),
            "corpus_position": getattr(case, "corpus_position", None),
            "local_position": getattr(case, "local_position", None),
            "expected_present": True,
            "recovered": bool(terms_ok and assets_ok),
            "best_ground_truth_rank": best_rank,
            "matched_terms": sorted(matched_terms),
            "matched_assets": sorted(matched_assets),
            "required_asset_hits": required_asset_hits,
        })
    return out


def failure_classification(
    points: list[dict[str, Any]], case_id: str, key: str
) -> dict[str, Any]:
    observations = [
        (float(point["requested_ratio"]), next(
            (x for x in point[key] if x["case_id"] == case_id), None
        ))
        for point in points
    ]
    present = [(ratio, diag) for ratio, diag in observations if diag and diag["expected_present"]]
    if not present:
        return {"classification": "not-applicable", "first_failure_scale": None}
    first_ratio, first_diag = present[0]
    if not first_diag["recovered"]:
        return {"classification": "baseline-incapable", "first_failure_scale": first_ratio}
    for ratio, diag in present[1:]:
        if not diag["recovered"]:
            return {"classification": "scale-regression", "first_failure_scale": ratio}
    return {"classification": "stable", "first_failure_scale": None}


def compare_live_to_lexical(
    lexical_cases: list[dict[str, Any]],
    live_results: list[Any],
) -> list[dict[str, Any]]:
    """Join already-scored live results to retrieval diagnostics without re-judging."""
    lexical_by_id = {row["case_id"]: row for row in lexical_cases}
    out: list[dict[str, Any]] = []
    for live in live_results:
        if not live.expected_present:
            continue
        lexical = lexical_by_id.get(live.case_id)
        lexical_recovered = None if lexical is None else lexical.get("recovered")
        if lexical_recovered is False and live.recovered:
            classification = "contextmesh-recovery-win"
        elif lexical_recovered is True and not live.recovered:
            classification = "contextmesh-regression"
        elif lexical_recovered is False and not live.recovered:
            classification = "shared-evidence-bottleneck"
        elif lexical_recovered is True and live.recovered:
            classification = "stable"
        else:
            classification = "baseline-unavailable"
        out.append({
            "case_id": live.case_id,
            "kind": live.kind.value,
            "lexical_recovered": lexical_recovered,
            "contextmesh_recovered": live.recovered,
            "term_recall": live.term_recall,
            "coverage": live.coverage,
            "visited_blocks": live.visited_blocks,
            "total_blocks": live.total_blocks,
            "judgment_valid": live.judgment_valid,
            "latency_seconds": live.latency_seconds,
            "classification": classification,
        })
    return out
