from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .judges import OpenAICompatibleJudge, _content_text
from .models import ContextBlock, Modality, ModelRoute, UsageMetrics


PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "capabilities": ["text", "table", "vision", "audio"],
        "native_video": False,
        "lmcache": False,
        "protocol": "openai-chat",
    },
    "anthropic": {
        "label": "Anthropic",
        "default_base_url": "https://api.anthropic.com/v1",
        "capabilities": ["text", "table", "vision"],
        "native_video": False,
        "lmcache": False,
        "protocol": "anthropic-messages",
    },
    "gemini": {
        "label": "Google Gemini",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "capabilities": ["text", "table", "vision", "audio", "video"],
        "native_video": True,
        "lmcache": False,
        "protocol": "gemini-generate-content",
    },
    "qwen": {
        "label": "Qwen / DashScope compatible",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "capabilities": ["text", "table", "vision", "audio"],
        "native_video": False,
        "lmcache": False,
        "protocol": "openai-chat",
    },
    "vllm": {
        "label": "Local vLLM",
        "default_base_url": "http://127.0.0.1:8000/v1",
        "capabilities": ["text", "table", "vision"],
        "native_video": False,
        "lmcache": True,
        "protocol": "openai-chat",
    },
    "sglang": {
        "label": "Local SGLang",
        "default_base_url": "http://127.0.0.1:30000/v1",
        "capabilities": ["text", "table", "vision"],
        "native_video": False,
        "lmcache": False,
        "protocol": "openai-chat",
    },
    "openai-compatible": {
        "label": "Generic OpenAI-compatible",
        "default_base_url": "http://127.0.0.1:8000/v1",
        "capabilities": ["text", "table"],
        "native_video": False,
        "lmcache": False,
        "protocol": "openai-chat",
    },
}


def provider_catalog() -> list[dict[str, Any]]:
    return [{"id": key, **value} for key, value in PROVIDER_CATALOG.items()]


def _read_media(block: ContextBlock, *, max_bytes: int = 20_000_000) -> tuple[str, str] | None:
    media_path = Path(str(block.metadata.get("media_path") or block.source.path))
    if not media_path.is_file() or media_path.stat().st_size > max_bytes:
        return None
    mime = block.metadata.get("media_mime")
    if not mime:
        mime, _ = mimetypes.guess_type(media_path.name)
    mime = str(mime or "application/octet-stream")
    return mime, base64.b64encode(media_path.read_bytes()).decode("ascii")


class AnthropicJudge(OpenAICompatibleJudge):
    """Anthropic Messages adapter while preserving ContextMesh's judge contract."""

    def _chat(self, messages: list[dict[str, Any]]) -> str:
        blocks: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                blocks.append({"type": "text", "text": content})
                continue
            for item in content or []:
                if item.get("type") == "text":
                    blocks.append({"type": "text", "text": item.get("text", "")})
                elif item.get("type") == "image_url":
                    url = str((item.get("image_url") or {}).get("url") or "")
                    if url.startswith("data:") and ";base64," in url:
                        head, data = url.split(",", 1)
                        media_type = head[5:].split(";", 1)[0]
                        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
        body = json.dumps({"model": self.model, "max_tokens": self.reserve_output_tokens, "temperature": 0, "messages": [{"role": "user", "content": blocks}]}).encode()
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/messages",
            data=body,
            headers={"Content-Type": "application/json", "x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.request_timeout_seconds) as resp:
            data = json.loads(resp.read().decode())
        self._usage.requests += 1
        self._usage.latency_seconds += time.perf_counter() - started
        usage = data.get("usage") or {}
        self._usage.prompt_tokens += int(usage.get("input_tokens") or 0)
        self._usage.completion_tokens += int(usage.get("output_tokens") or 0)
        self._usage.estimated_cost_usd = (
            self._usage.prompt_tokens * self.input_cost_per_million / 1_000_000
            + self._usage.completion_tokens * self.output_cost_per_million / 1_000_000
        )
        return "\n".join(str(x.get("text") or "") for x in data.get("content") or [] if isinstance(x, dict))

    def _direct_audio_payload(self, block: ContextBlock) -> dict[str, Any] | None:
        return None


class GeminiJudge(OpenAICompatibleJudge):
    """Gemini generateContent adapter with native image/audio/video inline payloads.

    Large media should later move through provider file handles; inline bytes keep the
    adapter dependency-free and make modality behavior explicit for the current PoC.
    """

    def _chat(self, messages: list[dict[str, Any]]) -> str:
        parts: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                parts.append({"text": content})
                continue
            for item in content or []:
                kind = item.get("type")
                if kind == "text":
                    parts.append({"text": item.get("text", "")})
                elif kind == "image_url":
                    url = str((item.get("image_url") or {}).get("url") or "")
                    if url.startswith("data:") and ";base64," in url:
                        head, data = url.split(",", 1)
                        parts.append({"inline_data": {"mime_type": head[5:].split(";", 1)[0], "data": data}})
                elif kind == "input_audio":
                    audio = item.get("input_audio") or {}
                    ext = str(audio.get("format") or "wav")
                    mime = "audio/mpeg" if ext == "mp3" else f"audio/{ext}"
                    parts.append({"inline_data": {"mime_type": mime, "data": audio.get("data", "")}})
                elif kind == "input_video":
                    video = item.get("input_video") or {}
                    parts.append({"inline_data": {"mime_type": video.get("mime_type", "video/mp4"), "data": video.get("data", "")}})
        key = urllib.parse.quote(self.api_key, safe="")
        url = f"{self.base_url.rstrip('/')}/models/{urllib.parse.quote(self.model, safe='')}:generateContent?key={key}"
        body = json.dumps({"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0}}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        started = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.request_timeout_seconds) as resp:
            data = json.loads(resp.read().decode())
        self._usage.requests += 1
        self._usage.latency_seconds += time.perf_counter() - started
        usage = data.get("usageMetadata") or {}
        self._usage.prompt_tokens += int(usage.get("promptTokenCount") or 0)
        self._usage.completion_tokens += int(usage.get("candidatesTokenCount") or 0)
        self._usage.cached_prompt_tokens += int(usage.get("cachedContentTokenCount") or 0)
        self._usage.estimated_cost_usd = (
            self._usage.prompt_tokens * self.input_cost_per_million / 1_000_000
            + self._usage.completion_tokens * self.output_cost_per_million / 1_000_000
        )
        candidate = (data.get("candidates") or [{}])[0]
        return "\n".join(str(p.get("text") or "") for p in ((candidate.get("content") or {}).get("parts") or []) if isinstance(p, dict))

    def can_inspect(self, block: ContextBlock) -> bool:
        if super().can_inspect(block):
            return True
        if block.modality == Modality.VIDEO and "video" in self.capabilities:
            return _read_media(block) is not None
        return False

    def build_block_content(self, question: str, answer: str, block: ContextBlock, *, text_override: str | None = None, slice_label: str | None = None) -> list[dict[str, Any]]:
        content = super().build_block_content(question, answer, block, text_override=text_override, slice_label=slice_label)
        if block.modality == Modality.VIDEO and "video" in self.capabilities:
            media = _read_media(block)
            if media:
                mime, data = media
                content.append({"type": "input_video", "input_video": {"mime_type": mime, "data": data}})
        return content


class OpenAIJudge(OpenAICompatibleJudge):
    pass


class QwenJudge(OpenAICompatibleJudge):
    pass


class VLLMJudge(OpenAICompatibleJudge):
    pass


def build_judge_from_route(route: ModelRoute) -> OpenAICompatibleJudge:
    api_key = os.getenv(route.api_key_env, "EMPTY") if route.api_key_env else "EMPTY"
    kwargs = dict(
        route_id=route.id,
        input_cost_per_million=route.input_cost_per_million,
        output_cost_per_million=route.output_cost_per_million,
        capabilities=route.capabilities,
        max_context_tokens=route.max_context_tokens,
        request_timeout_seconds=route.request_timeout_seconds,
    )
    provider = (route.provider or "openai-compatible").lower()
    cls: type[OpenAICompatibleJudge]
    if provider == "anthropic":
        cls = AnthropicJudge
    elif provider == "gemini":
        cls = GeminiJudge
    elif provider == "openai":
        cls = OpenAIJudge
    elif provider == "qwen":
        cls = QwenJudge
    elif provider in {"vllm", "sglang"}:
        cls = VLLMJudge
    else:
        cls = OpenAICompatibleJudge
    return cls(route.model, route.base_url, api_key, **kwargs)
