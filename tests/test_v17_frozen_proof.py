from __future__ import annotations

import pytest

from benchmarks.verify_frozen_public_proof import (
    FrozenProofMismatch,
    verify_frozen_public_proof,
)


def _fixtures():
    download = {
        "sources": [
            {"name": "a.pdf", "sha256": "aaa"},
            {"name": "b.xlsx", "sha256": "bbb"},
        ]
    }
    gate12 = {
        "sources": [
            {"name": "a.pdf", "sha256": "aaa"},
            {"name": "b.xlsx", "sha256": "bbb"},
        ]
    }
    preflight = {
        "corpus": {"model_context_tokens": 131072},
        "panel": {
            "selected_case_ids": ["n1", "n2"],
            "anchor_fingerprint": "anchor",
        },
        "points": [
            {
                "requested_ratio": 1.0,
                "actual_ratio": 1.01,
                "estimated_tokens": 132000,
                "selected_blocks": 10,
                "selected_assets": 2,
                "projection_fingerprint": "p1",
            },
            {
                "requested_ratio": 2.0,
                "actual_ratio": 2.02,
                "estimated_tokens": 265000,
                "selected_blocks": 20,
                "selected_assets": 2,
                "projection_fingerprint": "p2",
            },
        ],
    }
    plan = {
        "model_context_tokens": 131072,
        "selected_case_ids": ["n1", "n2"],
        "anchor_fingerprint": "anchor",
        "ready_for_live_gate4": True,
        "points": [
            {
                "requested_ratio": 1.0,
                "actual_ratio": 1.01,
                "estimated_tokens": 132000,
                "selected_blocks": 10,
                "selected_assets": 2,
                "projection_fingerprint": "p1",
            },
            {
                "requested_ratio": 2.0,
                "actual_ratio": 2.02,
                "estimated_tokens": 265000,
                "selected_blocks": 20,
                "selected_assets": 2,
                "projection_fingerprint": "p2",
            },
        ],
    }
    return download, plan, gate12, preflight


def test_frozen_public_proof_accepts_exact_rebuild():
    download, plan, gate12, preflight = _fixtures()

    report = verify_frozen_public_proof(
        download_manifest=download,
        gate4_plan=plan,
        gate12_proof=gate12,
        gate4_preflight=preflight,
    )

    assert report["verified"] is True
    assert report["provider_calls_made"] == 0
    assert report["source_hashes_match"] is True
    assert all(point["matches"] for point in report["point_checks"])


def test_frozen_public_proof_blocks_changed_source_before_provider_calls():
    download, plan, gate12, preflight = _fixtures()
    download["sources"][0]["sha256"] = "changed"

    with pytest.raises(FrozenProofMismatch, match="source-sha-set-mismatch"):
        verify_frozen_public_proof(
            download_manifest=download,
            gate4_plan=plan,
            gate12_proof=gate12,
            gate4_preflight=preflight,
        )


def test_frozen_public_proof_blocks_tampered_projection():
    download, plan, gate12, preflight = _fixtures()
    plan["points"][1]["projection_fingerprint"] = "tampered"

    with pytest.raises(FrozenProofMismatch, match="2x-projection_fingerprint-mismatch"):
        verify_frozen_public_proof(
            download_manifest=download,
            gate4_plan=plan,
            gate12_proof=gate12,
            gate4_preflight=preflight,
        )


def test_frozen_public_proof_blocks_panel_membership_drift():
    download, plan, gate12, preflight = _fixtures()
    plan["selected_case_ids"] = ["n2", "n1"]

    with pytest.raises(FrozenProofMismatch, match="selected-case-order-mismatch"):
        verify_frozen_public_proof(
            download_manifest=download,
            gate4_plan=plan,
            gate12_proof=gate12,
            gate4_preflight=preflight,
        )
