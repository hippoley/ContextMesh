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
                "ground_truth_ranks": [],
                "first_sufficient_rank": None,
                "failure_reason": "not-applicable",
                "matched_terms": [],
                "matched_assets": [],
            })
            continue

        ordered = reader.lexical_order(case.question)
        selected_ids = ordered[: max(0, top_k)]
        matched_terms: set[str] = set()
        matched_assets: set[str] = set()
        matched_target = False
        ground_truth_ranks: list[int] = []
        first_sufficient_rank: int | None = None

        required_asset_hits = case.required_asset_hits
        if required_asset_hits is None:
            required_asset_hits = (
                len(case.target_assets)
                if case.kind == NeedleKind.CROSS_FILE and case.target_assets
                else 1
            )

        cumulative_terms: set[str] = set()
        cumulative_assets: set[str] = set()
        for rank, block_id in enumerate(ordered, start=1):
            block = reader.read(block_id)
            if not _ground_truth_block_matches(block, case):
                continue
            ground_truth_ranks.append(rank)
            hits = _term_hits(block.text or "", case.match_terms)
            cumulative_terms.update(hits)
            if hits or not case.match_terms:
                cumulative_assets.add(Path(block.source.path).name)
            if case.match_terms:
                cumulative_terms_ok = (
                    len(cumulative_terms) == len(set(case.match_terms))
                    if case.match_all_terms
                    else bool(cumulative_terms)
                )
            else:
                cumulative_terms_ok = True
            if cumulative_terms_ok and len(cumulative_assets) >= required_asset_hits:
                first_sufficient_rank = rank
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

        assets_ok = len(matched_assets) >= required_asset_hits
        if terms_ok and assets_ok:
            failure_reason = "recovered"
        elif not matched_target:
            failure_reason = "candidate-miss"
        elif not terms_ok:
            failure_reason = "term-miss"
        else:
            failure_reason = "asset-miss"

        out.append({
            "case_id": case.id,
            "kind": case.kind.value,
            "modality": getattr(case, "modality", None),
            "corpus_position": getattr(case, "corpus_position", None),
            "local_position": getattr(case, "local_position", None),
            "expected_present": True,
            "recovered": bool(terms_ok and assets_ok),
            "best_ground_truth_rank": ground_truth_ranks[0] if ground_truth_ranks else None,
            "ground_truth_ranks": ground_truth_ranks,
            "first_sufficient_rank": first_sufficient_rank,
            "failure_reason": failure_reason,
            "matched_terms": sorted(matched_terms),
            "matched_assets": sorted(matched_assets),
            "required_asset_hits": required_asset_hits,
        })
    return out

