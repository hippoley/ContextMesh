from __future__ import annotations

import pytest

from contextmesh.judges import OpenAICompatibleJudge
from contextmesh.models import ModelRoute
from contextmesh.providers import build_judge_from_route
from contextmesh.token_budget import (
    TextTokenBudget,
    TokenBudgetExceeded,
    TokenCounterSpec,
)


def test_conservative_fallback_treats_cjk_as_at_least_one_token_per_char():
    budget = TextTokenBudget(
        max_context_tokens=1000,
        reserve_output_tokens=100,
        safety_factor=0.90,
        chars_per_token_estimate=1.0,
    )
    text = "这是一个用于验证中文上下文预算不会被三点二字符每token低估的句子。" * 20

    assert budget.mode == "conservative-char-estimate"
    assert budget.exact is False
    assert budget.count(text) == len(text)
    with pytest.raises(TokenBudgetExceeded):
        budget.assert_text_request("中" * 900)


def test_injected_exact_counter_drives_same_splitter_used_by_budget_gate():
    spec = TokenCounterSpec(
        counter=lambda text: len(text.encode("utf-8")),
        label="fake:utf8-bytes",
        exact=True,
    )
    budget = TextTokenBudget(
        max_context_tokens=100,
        reserve_output_tokens=10,
        safety_factor=1.0,
        chars_per_token_estimate=1.0,
        counter_spec=spec,
    )

    parts = budget.split_text("汉字ABC" * 40, budget_tokens=45, overlap_chars=0)

    assert len(parts) > 1
    assert all(budget.count(part) <= 45 for part in parts)
    assert budget.mode == "fake:utf8-bytes"
    assert budget.exact is True


def test_message_budget_counts_protocol_and_media_reserve():
    budget = TextTokenBudget(
        max_context_tokens=7000,
        reserve_output_tokens=500,
        safety_factor=1.0,
        chars_per_token_estimate=1.0,
    )
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "x" * 100},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }]

    total, detail = budget.count_messages(messages, media_reserve_tokens=4096)

    assert detail["media_items"] == 1
    assert detail["media_reserve_tokens"] == 4096
    assert detail["protocol_reserve_tokens"] > 0
    assert total > 4196


def test_openai_compatible_request_is_blocked_before_network():
    judge = OpenAICompatibleJudge(
        model="fake",
        base_url="http://127.0.0.1:9",
        max_context_tokens=1000,
        reserve_output_tokens=100,
        chars_per_token_estimate=1.0,
        token_budget_safety_factor=0.90,
    )

    with pytest.raises(TokenBudgetExceeded, match="exceeds ContextMesh token budget"):
        judge._chat([{"role": "user", "content": "中" * 900}])


def test_provider_factory_propagates_route_budget_contract():
    route = ModelRoute(
        id="route-budget",
        label="Budgeted local route",
        provider="openai-compatible",
        base_url="http://127.0.0.1:8000/v1",
        model="local-model",
        max_context_tokens=32768,
        tokenizer_spec=None,
        token_budget_safety_factor=0.82,
        chars_per_token_estimate=0.75,
    )

    judge = build_judge_from_route(route)
    status = judge.token_budget_status()

    assert status["max_context_tokens"] == 32768
    assert status["safety_factor"] == pytest.approx(0.82)
    assert status["chars_per_token_estimate"] == pytest.approx(0.75)
    assert status["mode"] == "conservative-char-estimate"
    assert status["exact_text"] is False


def test_route_with_missing_optional_tiktoken_fails_closed_when_not_installed(monkeypatch):
    # The loader must never silently downgrade an explicitly requested exact tokenizer.
    import builtins
    from contextmesh.token_budget import load_token_counter

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ValueError, match="optional tokenizers extra"):
        load_token_counter("tiktoken:model", model="gpt-4o")
