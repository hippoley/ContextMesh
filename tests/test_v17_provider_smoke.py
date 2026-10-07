from __future__ import annotations

import json
import urllib.error

import pytest

from contextmesh.provider_smoke import (
    ProviderSmokeError,
    magenta_png_data_url,
    smoke_openai_compatible,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_magenta_png_is_data_url_without_external_asset_dependency():
    value = magenta_png_data_url(8, 8)
    assert value.startswith("data:image/png;base64,")
    assert len(value) > 80


def test_provider_smoke_uses_two_calls_and_never_records_credential():
    calls = []
    secret = "test-secret-that-must-not-leak"

    def opener(request, timeout):
        calls.append(
            {
                "url": request.full_url,
                "authorization": request.get_header("Authorization"),
                "body": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        if len(calls) == 1:
            return _Response(
                {
                    "choices": [{"message": {"content": "TEXT_OK"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 1,
                        "total_tokens": 11,
                    },
                }
            )
        return _Response(
            {
                "choices": [{"message": {"content": "MAGENTA"}}],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 1,
                    "total_tokens": 21,
                },
            }
        )

    result = smoke_openai_compatible(
        base_url="https://workspace.example/compatible-mode/v1",
        model="qwen3-vl-8b-instruct",
        api_key=secret,
        opener=opener,
    )

    assert result.provider_calls == 2
    assert result.text_ok is True
    assert result.vision_ok is True
    assert result.total_tokens == 32
    assert len(calls) == 2
    assert all(call["authorization"] == f"Bearer {secret}" for call in calls)
    assert calls[0]["url"].endswith("/chat/completions")
    assert calls[1]["body"]["messages"][0]["content"][0]["type"] == "image_url"
    serialized = json.dumps(result.as_dict())
    assert secret not in serialized
    assert result.as_dict()["credential_material_recorded"] is False


def test_provider_smoke_rejects_non_https_before_any_call():
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        raise AssertionError("must not call network")

    with pytest.raises(ProviderSmokeError, match="HTTPS"):
        smoke_openai_compatible(
            base_url="http://workspace.example/compatible-mode/v1",
            model="qwen3-vl-8b-instruct",
            api_key="secret",
            opener=opener,
        )

    assert calls == []


def test_provider_smoke_failure_does_not_echo_secret():
    secret = "sensitive-smoke-secret"

    def opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=None,
        )

    with pytest.raises(ProviderSmokeError) as exc:
        smoke_openai_compatible(
            base_url="https://workspace.example/compatible-mode/v1",
            model="qwen3-vl-8b-instruct",
            api_key=secret,
            opener=opener,
        )

    assert secret not in str(exc.value)
    assert "HTTP 401" in str(exc.value)


def test_vision_failure_preserves_completed_text_call_usage():
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            return _Response(
                {
                    "choices": [{"message": {"content": "TEXT_OK"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 1,
                        "total_tokens": 11,
                    },
                }
            )
        raise urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", hdrs=None, fp=None
        )

    with pytest.raises(ProviderSmokeError) as exc:
        smoke_openai_compatible(
            base_url="https://workspace.example/compatible-mode/v1",
            model="qwen3-vl-8b-instruct",
            api_key="secret",
            opener=opener,
        )

    evidence = exc.value.evidence()
    assert len(calls) == 2
    assert evidence["provider_attempts"] == 2
    assert evidence["provider_calls"] == 1
    assert evidence["prompt_tokens"] == 10
    assert evidence["completion_tokens"] == 1
    assert evidence["total_tokens"] == 11
    assert evidence["failed_stage"] == "vision"


def test_text_validation_failure_counts_completed_call_and_usage():
    def opener(request, timeout):
        return _Response(
            {
                "choices": [{"message": {"content": "WRONG"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
            }
        )

    with pytest.raises(ProviderSmokeError) as exc:
        smoke_openai_compatible(
            base_url="https://workspace.example/compatible-mode/v1",
            model="qwen3-vl-8b-instruct",
            api_key="secret",
            opener=opener,
        )

    assert exc.value.evidence() == {
        "provider_attempts": 1,
        "provider_calls": 1,
        "prompt_tokens": 8,
        "completion_tokens": 2,
        "total_tokens": 10,
        "failed_stage": "text-validation",
    }


def test_vision_validation_failure_counts_both_completed_calls_and_usage():
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _Response(
                {
                    "choices": [{"message": {"content": "TEXT_OK"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
                }
            )
        return _Response(
            {
                "choices": [{"message": {"content": "BLUE"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22},
            }
        )

    with pytest.raises(ProviderSmokeError) as exc:
        smoke_openai_compatible(
            base_url="https://workspace.example/compatible-mode/v1",
            model="qwen3-vl-8b-instruct",
            api_key="secret",
            opener=opener,
        )

    assert exc.value.evidence() == {
        "provider_attempts": 2,
        "provider_calls": 2,
        "prompt_tokens": 30,
        "completion_tokens": 3,
        "total_tokens": 33,
        "failed_stage": "vision-validation",
    }


def test_http_failure_records_attempt_without_completed_call():
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", hdrs=None, fp=None)

    with pytest.raises(ProviderSmokeError) as exc:
        smoke_openai_compatible(
            base_url="https://workspace.example/compatible-mode/v1",
            model="qwen3-vl-8b-instruct",
            api_key="secret",
            opener=opener,
        )

    evidence = exc.value.evidence()
    assert evidence["provider_attempts"] == 1
    assert evidence["provider_calls"] == 0
    assert evidence["failed_stage"] == "pre-call"
