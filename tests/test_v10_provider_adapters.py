from contextmesh.models import ModelRoute
from contextmesh.providers import (
    AnthropicJudge,
    GeminiJudge,
    OpenAIJudge,
    VLLMJudge,
    build_judge_from_route,
    provider_catalog,
)


def route(provider: str, caps=None):
    return ModelRoute(
        id=f"r-{provider}", label=provider, provider=provider,
        base_url="http://example.invalid/v1", model="model",
        capabilities=caps or ["text", "table"],
    )


def test_provider_catalog_exposes_explicit_protocols():
    items = {x["id"]: x for x in provider_catalog()}
    assert items["gemini"]["native_video"] is True
    assert items["vllm"]["lmcache"] is True
    assert items["anthropic"]["protocol"] == "anthropic-messages"


def test_factory_selects_provider_specific_adapters():
    assert isinstance(build_judge_from_route(route("gemini", ["text", "video"])), GeminiJudge)
    assert isinstance(build_judge_from_route(route("anthropic", ["text", "vision"])), AnthropicJudge)
    assert isinstance(build_judge_from_route(route("openai")), OpenAIJudge)
    assert isinstance(build_judge_from_route(route("vllm")), VLLMJudge)


def test_model_route_new_fields_are_backward_compatible():
    r = route("openai-compatible")
    assert r.deployment == "cloud"
    assert r.prompt_cache is False
    assert r.native_file_handles is False
