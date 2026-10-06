from pathlib import Path


def test_offline_gate4_report_exposes_evidence_sufficiency() -> None:
    source = Path("benchmarks/run_gate4_offline_retrieval_curve.py").read_text(encoding="utf-8")
    assert "## Case evidence sufficiency (lexical top-20)" in source
    assert "First hit" in source
    assert "Sufficient rank" in source
    assert 'case.get("first_sufficient_rank")' in source
    assert 'case.get("failure_reason")' in source
