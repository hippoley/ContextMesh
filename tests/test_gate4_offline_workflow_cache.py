from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/gate4-offline-retrieval-curve.yml")


def test_gate4_offline_workflow_caches_only_frozen_source_downloads() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/cache@v4" in source
    assert "path: /tmp/contextmesh-nist-proof/downloads" in source
    assert "benchmarks/big-context/nist-public-corpus.json" in source
    assert "benchmarks/results/nist-public-gate1-2-v2-2026-09-28.json" in source
    assert "benchmarks/results/nist-public-gate4-preflight-v2-2026-09-28.json" in source
    assert "--reuse-downloads" in source


def test_gate4_offline_workflow_still_reverifies_cached_inputs() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    cache_index = source.index("Restore frozen NIST source downloads")
    build_index = source.index("Rebuild official bounded-table NIST v2 corpus")
    verify_index = source.index("Verify rebuilt plan against committed frozen proof")

    assert cache_index < build_index < verify_index
    assert "verify_frozen_public_proof.py" in source
