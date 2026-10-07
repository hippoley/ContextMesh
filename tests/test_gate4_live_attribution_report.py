from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "contextmesh_gate4_live_attribution_report",
    ROOT / "benchmarks" / "report_gate4_live_attribution.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

build_live_attribution_report = MODULE.build_live_attribution_report
render_markdown = MODULE.render_markdown


def _point(
    scale: float,
    classification: str,
    *,
    lexical_recovered: bool,
    contextmesh_recovered: bool,
) -> dict:
    return {
        "requested_ratio": scale,
        "status": "pass",
        "case_attribution": {
            "lexical-top-20": [
                {
                    "case_id": "cross-file-008",
                    "kind": "cross-file",
                    "classification": classification,
                    "lexical_recovered": lexical_recovered,
                    "contextmesh_recovered": contextmesh_recovered,
                    "lexical_best_ground_truth_rank": (
                        12 if scale == 1 else 22
                    ),
                    "lexical_first_sufficient_rank": (
                        13 if scale == 1 else 26
                    ),
                    "lexical_failure_reason": (
                        "recovered"
                        if lexical_recovered
                        else "candidate-miss"
                    ),
                    "term_recall": (
                        1.0 if contextmesh_recovered else 0.0
                    ),
                    "coverage": 1.0,
                    "judgment_valid": True,
                    "latency_seconds": 0.2,
                }
            ]
        },
    }


def test_report_accepts_full_proof_report_and_summarizes_transition() -> None:
    payload = {
        "schema_version": 1,
        "gate4": {
            "points": [
                _point(
                    1,
                    "stable",
                    lexical_recovered=True,
                    contextmesh_recovered=True,
                ),
                _point(
                    2,
                    "shared-evidence-bottleneck",
                    lexical_recovered=False,
                    contextmesh_recovered=False,
                ),
            ]
        },
    }

    report = build_live_attribution_report(payload)

    assert report["evidence_class"] == (
        "contextmesh-gate4-live-attribution-frontiers"
    )
    assert report["provider_calls_made_by_reporter"] == 0
    assert report["observed_cases"] == 1
    assert report["transition_count"] == 1
    assert report["status_counts"] == {
        "shared-retrieval-bottleneck": 1
    }

    row = next(
        item
        for item in report["frontiers"]
        if item["baseline"] == "lexical-top-20"
    )
    assert row["case_id"] == "cross-file-008"
    assert row["last_stable_scale"] == 1
    assert row["first_transition_scale"] == 2
    assert row["transition"]["lexical_first_sufficient_rank"] == 26


def test_report_accepts_bare_gate4_report() -> None:
    payload = {
        "points": [
            _point(
                1,
                "stable",
                lexical_recovered=True,
                contextmesh_recovered=True,
            ),
            _point(
                2,
                "contextmesh-recovery-win",
                lexical_recovered=False,
                contextmesh_recovered=True,
            ),
        ]
    }

    report = build_live_attribution_report(payload)

    assert report["status_counts"] == {
        "contextmesh-rescues-retrieval": 1
    }


def test_report_rejects_payload_without_gate4_points() -> None:
    try:
        build_live_attribution_report({"gate4": {}})
    except ValueError as exc:
        assert "gate4.points" in str(exc)
    else:
        raise AssertionError("invalid proof payload unexpectedly accepted")


def test_markdown_surfaces_first_transition_and_rank_evidence() -> None:
    report = build_live_attribution_report(
        {
            "points": [
                _point(
                    1,
                    "stable",
                    lexical_recovered=True,
                    contextmesh_recovered=True,
                ),
                _point(
                    2,
                    "contextmesh-regression",
                    lexical_recovered=True,
                    contextmesh_recovered=False,
                ),
            ]
        }
    )

    markdown = render_markdown(report)

    assert "Gate 4 Live Attribution Frontiers" in markdown
    assert "cross-file-008" in markdown
    assert "contextmesh-regresses-despite-evidence" in markdown
    assert "2x" in markdown
    assert "26" in markdown
    assert "reporter makes no provider call" in markdown
