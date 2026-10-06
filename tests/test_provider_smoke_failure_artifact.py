from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

import pytest

from contextmesh.provider_smoke import ProviderSmokeError


def _load_script():
    path = Path("benchmarks/smoke_live_provider.py")
    spec = spec_from_file_location("smoke_live_provider_script", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_smoke_failure_is_persisted_without_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    secret = "super-secret-provider-key"
    output = tmp_path / "provider-smoke.json"
    monkeypatch.setenv("TEST_PROVIDER_KEY", secret)

    def fail(**kwargs):
        assert kwargs["api_key"] == secret
        raise ProviderSmokeError("provider returned HTTP 401 for https://example.test/v1/chat/completions")

    monkeypatch.setattr(script, "smoke_openai_compatible", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_live_provider.py",
            "--base-url",
            "https://example.test/v1",
            "--model",
            "test-model",
            "--api-key-env",
            "TEST_PROVIDER_KEY",
            "--output",
            str(output),
        ],
    )

    assert script.main() == 3
    payload = json.loads(output.read_text(encoding="utf-8"))
    captured = capsys.readouterr()

    assert payload["status"] == "failed"
    assert payload["credential_material_recorded"] is False
    assert "HTTP 401" in payload["error"]
    assert secret not in output.read_text(encoding="utf-8")
    assert secret not in captured.out
    assert secret not in captured.err
    assert "PROVIDER_SMOKE_FAIL" in captured.out


def test_missing_credential_still_makes_no_smoke_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _load_script()
    output = tmp_path / "provider-smoke.json"
    monkeypatch.delenv("ABSENT_PROVIDER_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_live_provider.py",
            "--base-url",
            "https://example.test/v1",
            "--model",
            "test-model",
            "--api-key-env",
            "ABSENT_PROVIDER_KEY",
            "--output",
            str(output),
        ],
    )

    assert script.main() == 2
    assert not output.exists()


def test_live_manifest_distinguishes_failed_smoke(tmp_path: Path) -> None:
    smoke = tmp_path / "provider-smoke.json"
    smoke.write_text(
        '{"schema_version":1,"status":"failed","credential_material_recorded":false}\n',
        encoding="utf-8",
    )
    path = Path("benchmarks/summarize_big_context_live_run.py")
    spec = spec_from_file_location("summarize_live_run_for_smoke_test", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = module.build_manifest(
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
    assert manifest["stage"] == "provider-smoke-failed"
    assert manifest["provider_calls"] == 0
