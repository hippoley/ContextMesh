from pathlib import Path

from benchmarks.summarize_big_context_live_run import build_manifest


def test_manifest_surfaces_provider_configuration_blocker(tmp_path: Path) -> None:
    (tmp_path / "provider-blocker.json").write_text(
        '{"schema_version":1,"status":"blocked","stage":"provider-configuration",'
        '"reason":"missing-provider-credential","provider":"dashscope"}\n',
        encoding="utf-8",
    )
    manifest = build_manifest(
        tmp_path,
        run_id="123",
        git_sha="abc",
        provider="dashscope",
        model="qwen",
        context_tokens=131072,
        workers=6,
        smoke_only=True,
        run_scale=False,
    )
    assert manifest["stage"] == "provider-configuration-blocked"
    assert manifest["provider_blocker"]["reason"] == "missing-provider-credential"
    assert manifest["provider_calls"] == 0
    assert manifest["credential_material_recorded"] is False


def test_workflow_persists_missing_credentials_without_secret_material() -> None:
    workflow = Path(".github/workflows/big-context-live-proof.yml").read_text(encoding="utf-8")
    assert workflow.count("provider-blocker.json") >= 2
    assert workflow.count('"reason":"missing-provider-credential"') >= 2
