from __future__ import annotations

from pathlib import Path

from contextmesh.big_context_proof import CorpusPosition, LocalPosition, Modality, NeedleCase, NeedleKind
from contextmesh.gate4_diagnostics import lexical_case_diagnostics
from contextmesh.ingest import ingest_paths
from contextmesh.store import FileContextStore


def test_cross_file_rank_means_sufficient_evidence_not_first_hit(tmp_path: Path) -> None:
    first = tmp_path / "alpha.txt"
    second = tmp_path / "beta.txt"
    noise = tmp_path / "noise.txt"
    first.write_text("shared query alpha_marker decisive_alpha", encoding="utf-8")
    second.write_text("shared query beta_marker decisive_beta", encoding="utf-8")
    noise.write_text("shared query filler filler filler", encoding="utf-8")

    store = FileContextStore(tmp_path / "store")
    ingest_paths([first, second, noise], store, "rank-contract")
    case = NeedleCase(
        id="cross",
        kind=NeedleKind.CROSS_FILE,
        question="shared query alpha_marker beta_marker",
        target_assets=["alpha.txt", "beta.txt"],
        expected_present=True,
        match_terms=["decisive_alpha", "decisive_beta"],
        match_all_terms=True,
        required_asset_hits=2,
        corpus_position=CorpusPosition.MIDDLE,
        local_position=LocalPosition.MIDDLE,
        modality=Modality.TEXT,
    )

    row = lexical_case_diagnostics(store, "rank-contract", [case], top_k=1)[0]
    assert row["best_ground_truth_rank"] is not None
    assert row["first_sufficient_rank"] is not None
    assert row["first_sufficient_rank"] > row["best_ground_truth_rank"]
    assert len(row["ground_truth_ranks"]) >= 2
    assert row["recovered"] is False
    assert row["failure_reason"] in {"term-miss", "asset-miss"}


def test_negative_case_rank_fields_are_not_applicable(tmp_path: Path) -> None:
    p = tmp_path / "doc.txt"
    p.write_text("ordinary text", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    ingest_paths([p], store, "negative-contract")
    case = NeedleCase(
        id="negative",
        kind=NeedleKind.NEGATIVE,
        question="missing marker",
        expected_present=False,
        match_terms=["missing"],
        corpus_position=CorpusPosition.EARLY,
        local_position=LocalPosition.HEAD,
        modality=Modality.TEXT,
    )
    row = lexical_case_diagnostics(store, "negative-contract", [case], top_k=5)[0]
    assert row["ground_truth_ranks"] == []
    assert row["first_sufficient_rank"] is None
    assert row["failure_reason"] == "not-applicable"
