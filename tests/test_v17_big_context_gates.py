from pathlib import Path

from contextmesh.big_context_proof import (
    CorpusPosition,
    Gate1CorpusSpec,
    Gate2NeedleSpec,
    LocalPosition,
    NeedleCase,
    NeedleKind,
    evaluate_gate1_corpus,
    validate_needle_matrix,
)
from contextmesh.ingest import ingest_paths
from contextmesh.models import Modality
from contextmesh.store import FileContextStore


def _realish_corpus(tmp_path: Path):
    paths = []
    for i in range(4):
        p = tmp_path / f"policy-{i}.txt"
        p.write_text(("policy clause and exception " * 120) + f"needle-{i}", encoding="utf-8")
        paths.append(p)
    for i in range(3):
        p = tmp_path / f"record-{i}.json"
        p.write_text('{"status":"active","detail":"' + ("x" * 3200) + '"}', encoding="utf-8")
        paths.append(p)
    for i in range(3):
        p = tmp_path / f"table-{i}.csv"
        p.write_text("key,value\n" + "\n".join(f"k{j},v{j}" for j in range(500)), encoding="utf-8")
        paths.append(p)

    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(paths, store, "gate1-realish")
    return store, manifest


def test_gate1_requires_real_asset_count_hashes_formats_and_over_context_ratio(tmp_path: Path):
    _, manifest = _realish_corpus(tmp_path)
    report = evaluate_gate1_corpus(
        manifest,
        Gate1CorpusSpec(
            min_assets=10,
            max_assets=30,
            min_format_families=2,
            model_context_tokens=1000,
            min_corpus_to_context_ratio=5.0,
        ),
    )

    assert report.status == "pass"
    assert report.assets == 10
    assert report.source_hash_coverage == 1.0
    assert set(report.format_families) >= {"text", "table"}
    assert report.corpus_to_context_ratio >= 5.0


def test_gate1_fails_when_corpus_does_not_qualify(tmp_path: Path):
    p = tmp_path / "only.txt"
    p.write_text("tiny corpus", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([p], store, "too-small")

    report = evaluate_gate1_corpus(
        manifest,
        Gate1CorpusSpec(
            min_assets=10,
            max_assets=30,
            min_format_families=3,
            model_context_tokens=128000,
            min_corpus_to_context_ratio=5.0,
        ),
    )

    assert report.status == "fail"
    assert any(x.startswith("assets:") for x in report.blockers)
    assert any(x.startswith("format-families:") for x in report.blockers)
    assert any(x.startswith("corpus/context-ratio:") for x in report.blockers)


def test_gate2_matrix_requires_kind_and_position_coverage():
    cases = []
    kinds = list(NeedleKind)
    corpus_positions = list(CorpusPosition)
    local_positions = list(LocalPosition)

    for i in range(108):
        kind = kinds[i % len(kinds)]
        cases.append(
            NeedleCase(
                id=f"n-{i:03d}",
                kind=kind,
                question=f"Question {i}",
                target_assets=[f"asset-{i % 12}.txt"],
                expected_present=kind != NeedleKind.NEGATIVE,
                expected_answer=f"answer-{i}",
                match_terms=[f"marker-{i}"],
                corpus_position=corpus_positions[i % len(corpus_positions)],
                local_position=local_positions[(i // len(corpus_positions)) % len(local_positions)],
                modality=Modality.TEXT,
            )
        )

    report = validate_needle_matrix(cases, Gate2NeedleSpec(min_cases=100, min_kinds=8))

    assert report.status == "pass"
    assert report.total_cases == 108
    assert report.kind_counts["negative"] > 0
    assert report.kind_counts["cross-file"] > 0
    assert set(report.corpus_position_counts) == {"early", "middle", "late"}
    assert set(report.local_position_counts) == {"head", "middle", "tail"}


def test_gate2_rejects_a_large_but_shallow_matrix():
    cases = [
        NeedleCase(
            id=f"exact-{i}",
            kind=NeedleKind.EXACT,
            question="Find marker",
            target_assets=["one.txt"],
            expected_present=True,
            match_terms=[f"m{i}"],
            corpus_position=CorpusPosition.EARLY,
            local_position=LocalPosition.HEAD,
        )
        for i in range(120)
    ]

    report = validate_needle_matrix(cases)

    assert report.status == "fail"
    assert any(x.startswith("needle-kinds:") for x in report.blockers)
    assert "missing-corpus-position:middle" in report.blockers
    assert "missing-local-position:tail" in report.blockers
    assert "missing-kind:negative" in report.blockers
    assert "missing-kind:cross-file" in report.blockers
