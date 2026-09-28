from __future__ import annotations

import pytest

from contextmesh.frozen_proof import (
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



def test_frozen_v2_blocks_full_benchmark_drift_before_provider_calls():
    import hashlib
    import json

    download, plan, gate12, preflight = _fixtures()
    corpus = {"required_block_ids": ["b1", "b2", "b3"]}
    needles = {
        "cases": [
            {"id": "n1", "question": "q1"},
            {"id": "n2", "question": "q2"},
        ]
    }
    tasks = {
        "cases": [
            {"id": "t1", "question": "q", "candidate_answer": "a"},
        ]
    }

    def canonical(value):
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    gate12["frozen_fingerprints"] = {
        "coverage_fingerprint": hashlib.sha256(
            "\n".join(corpus["required_block_ids"]).encode("utf-8")
        ).hexdigest(),
        "needle_matrix_fingerprint": canonical(needles["cases"]),
        "task_set_fingerprint": canonical(tasks["cases"]),
    }

    ok = verify_frozen_public_proof(
        download_manifest=download,
        gate4_plan=plan,
        gate12_proof=gate12,
        gate4_preflight=preflight,
        corpus_manifest=corpus,
        needle_matrix=needles,
        task_cases=tasks,
    )
    assert ok["verified"] is True
    assert all(
        check["matches"] for check in ok["fingerprint_checks"].values()
    )

    changed_corpus = {"required_block_ids": ["b1", "b3"]}
    with pytest.raises(FrozenProofMismatch, match="coverage-fingerprint-mismatch"):
        verify_frozen_public_proof(
            download_manifest=download,
            gate4_plan=plan,
            gate12_proof=gate12,
            gate4_preflight=preflight,
            corpus_manifest=changed_corpus,
            needle_matrix=needles,
            task_cases=tasks,
        )

    changed_needles = {
        "cases": [
            {"id": "n1", "question": "q1 CHANGED"},
            {"id": "n2", "question": "q2"},
        ]
    }
    with pytest.raises(FrozenProofMismatch, match="needle-matrix-fingerprint-mismatch"):
        verify_frozen_public_proof(
            download_manifest=download,
            gate4_plan=plan,
            gate12_proof=gate12,
            gate4_preflight=preflight,
            corpus_manifest=corpus,
            needle_matrix=changed_needles,
            task_cases=tasks,
        )

    changed_tasks = {
        "cases": [
            {"id": "t1", "question": "q", "candidate_answer": "changed"},
        ]
    }
    with pytest.raises(FrozenProofMismatch, match="task-set-fingerprint-mismatch"):
        verify_frozen_public_proof(
            download_manifest=download,
            gate4_plan=plan,
            gate12_proof=gate12,
            gate4_preflight=preflight,
            corpus_manifest=corpus,
            needle_matrix=needles,
            task_cases=changed_tasks,
        )


def test_frozen_v2_requires_fingerprint_inputs_when_frozen_proof_declares_them():
    download, plan, gate12, preflight = _fixtures()
    gate12["frozen_fingerprints"] = {
        "coverage_fingerprint": "x",
        "needle_matrix_fingerprint": "y",
        "task_set_fingerprint": "z",
    }

    with pytest.raises(FrozenProofMismatch) as exc:
        verify_frozen_public_proof(
            download_manifest=download,
            gate4_plan=plan,
            gate12_proof=gate12,
            gate4_preflight=preflight,
        )

    message = str(exc.value)
    assert "coverage-fingerprint-input-missing" in message
    assert "needle-matrix-fingerprint-input-missing" in message
    assert "task-set-fingerprint-input-missing" in message
