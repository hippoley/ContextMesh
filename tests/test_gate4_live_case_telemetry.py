from __future__ import annotations

from contextmesh.big_context_proof import NeedleKind, NeedleRunResult
from contextmesh.gate4_diagnostics import compare_live_to_lexical


def _live(case_id: str, recovered: bool) -> NeedleRunResult:
    return NeedleRunResult(
        case_id=case_id,
        kind=NeedleKind.EXACT,
        expected_present=True,
        recovered=recovered,
        term_recall=1.0 if recovered else 0.0,
        coverage=1.0,
        judgment_valid=True,
    )


def test_compare_live_to_lexical_four_quadrants() -> None:
    lexical = [
        {"case_id": "win", "recovered": False},
        {"case_id": "regress", "recovered": True},
        {"case_id": "shared", "recovered": False},
        {"case_id": "stable", "recovered": True},
    ]
    rows = compare_live_to_lexical(
        lexical,
        [_live("win", True), _live("regress", False), _live("shared", False), _live("stable", True)],
    )
    assert {row["case_id"]: row["classification"] for row in rows} == {
        "win": "contextmesh-recovery-win",
        "regress": "contextmesh-regression",
        "shared": "shared-evidence-bottleneck",
        "stable": "stable",
    }


def test_compare_live_to_lexical_does_not_mutate_scored_result() -> None:
    live = _live("case", True)
    before = live.model_dump()
    compare_live_to_lexical([{"case_id": "case", "recovered": False}], [live])
    assert live.model_dump() == before
