from pathlib import Path
import json
import importlib.util


MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "summarize_big_context_live_run.py"
spec = importlib.util.spec_from_file_location("live_manifest", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_live_run_manifest_distinguishes_preflight_smoke_and_proof(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "cost-estimate.json").write_text(
        json.dumps({"estimated_cost_cny": 12.5, "within_budget": True}),
        encoding="utf-8",
    )

    preflight = mod.build_manifest(
        result_dir,
        run_id="123",
        git_sha="abc",
        provider="dashscope",
        model="qwen",
        context_tokens=131072,
        workers=6,
        smoke_only=True,
        run_scale=False,
    )
    assert preflight["stage"] == "preflight-complete-no-provider"
    assert preflight["provider_calls"] == 0
    assert preflight["estimated_cost_cny"] == 12.5

    (result_dir / "provider-smoke.json").write_text(
        json.dumps({"provider_calls": 2, "total_tokens": 77}),
        encoding="utf-8",
    )
    smoke = mod.build_manifest(
        result_dir,
        run_id="123",
        git_sha="abc",
        provider="dashscope",
        model="qwen",
        context_tokens=131072,
        workers=6,
        smoke_only=True,
        run_scale=False,
    )
    assert smoke["stage"] == "provider-smoke-complete"
    assert smoke["provider_calls"] == 2
    assert smoke["provider_tokens"] == 77

    (result_dir / "live-proof.json").write_text(
        json.dumps({
            "claim_proven": False,
            "gate1": {"status": "pass"},
            "gate2": {"status": "pass"},
            "gate3": {"status": "pass"},
            "gate4": {"status": "not-run"},
            "gate5": {"status": "not-run"},
        }),
        encoding="utf-8",
    )
    proof = mod.build_manifest(
        result_dir,
        run_id="123",
        git_sha="abc",
        provider="dashscope",
        model="qwen",
        context_tokens=131072,
        workers=6,
        smoke_only=False,
        run_scale=False,
    )
    assert proof["stage"] == "live-proof-complete"
    assert proof["claim_proven"] is False
    assert proof["gate_statuses"]["gate3"] == "pass"
    assert proof["credential_material_recorded"] is False


def test_live_run_manifest_surfaces_evidence_readiness_without_rejudging(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "evidence-check.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "decision": "hold",
                "reasons": ["gate4:not-run"],
                "policy": "evidence-readiness-only-not-promotion",
            }
        ),
        encoding="utf-8",
    )

    manifest = mod.build_manifest(
        result_dir,
        run_id="456",
        git_sha="def",
        provider="dashscope",
        model="qwen",
        context_tokens=131072,
        workers=6,
        smoke_only=True,
        run_scale=False,
    )

    assert manifest["evidence_readiness"] == "hold"
    assert manifest["evidence_readiness_reasons"] == ["gate4:not-run"]
    assert manifest["evidence_readiness_policy"] == "evidence-readiness-only-not-promotion"
    assert manifest["promotion_decision"] is None


def test_live_run_manifest_does_not_treat_failed_verification_file_as_verified(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "frozen-proof-verification.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "verified": False,
                "error": "fingerprint mismatch",
                "provider_calls_made": 0,
            }
        ),
        encoding="utf-8",
    )

    manifest = mod.build_manifest(
        result_dir,
        run_id="789",
        git_sha="ghi",
        provider="dashscope",
        model="qwen",
        context_tokens=131072,
        workers=6,
        smoke_only=True,
        run_scale=False,
    )

    assert manifest["stage"] == "frozen-proof-verification-failed"
    assert manifest["frozen_proof_verified"] is False


def test_live_run_manifest_requires_explicit_true_for_frozen_verification(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "frozen-proof-verification.json").write_text(
        json.dumps({"schema_version": 1, "verified": True}),
        encoding="utf-8",
    )

    manifest = mod.build_manifest(
        result_dir,
        run_id="790",
        git_sha="jkl",
        provider="dashscope",
        model="qwen",
        context_tokens=131072,
        workers=6,
        smoke_only=True,
        run_scale=False,
    )

    assert manifest["frozen_proof_verified"] is True
