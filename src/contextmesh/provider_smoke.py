from __future__ import annotations

import base64
import json
import struct
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Any, Callable


class ProviderSmokeError(RuntimeError):
    def __init__(self, message: str, *, provider_calls: int = 0, prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0, stage: str = "pre-call") -> None:
        super().__init__(message)
        self.provider_calls = provider_calls
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.stage = stage

    def evidence(self) -> dict[str, Any]:
        return {"provider_calls": self.provider_calls, "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens, "total_tokens": self.total_tokens, "failed_stage": self.stage}



@dataclass(frozen=True)
class ProviderSmokeResult:
    model: str
    base_url: str
    text_ok: bool
    vision_ok: bool
    provider_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float
    text_response: str
    vision_response: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "model": self.model,
            "base_url": self.base_url,
            "text_ok": self.text_ok,
            "vision_ok": self.vision_ok,
            "provider_calls": self.provider_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_seconds": round(self.latency_seconds, 3),
            "text_response": self.text_response,
            "vision_response": self.vision_response,
            "credential_material_recorded": False,
        }


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return (
        struct.pack(">I", len(data))
        + payload
        + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    )


def magenta_png_data_url(width: int = 16, height: int = 16) -> str:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # PNG truecolor scanline: filter byte + RGB pixels.
    row = b"\x00" + (b"\xff\x00\xff" * width)
    raw = row * height
    png = signature + _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", zlib.compress(raw, level=9))
    png += _png_chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _extract_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _usage(payload: dict[str, Any]) -> tuple[int, int, int]:
    usage = payload.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    return prompt, completion, total


def _post_json(
    url: str,
    api_key: str,
    body: dict[str, Any],
    *,
    timeout: float,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ContextMesh-BigContextSmoke/1.0",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # Never include response headers or request headers in the exception because
        # credentials belong only in the Authorization header.
        raise ProviderSmokeError(
            f"provider returned HTTP {exc.code} for {url}"
        ) from exc
    except Exception as exc:
        raise ProviderSmokeError(
            f"provider request failed for {url}: {type(exc).__name__}"
        ) from exc

    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ProviderSmokeError(
            f"provider returned non-JSON content for {url}"
        ) from exc
    if not isinstance(obj, dict):
        raise ProviderSmokeError("provider JSON response must be an object")
    return obj


def smoke_openai_compatible(
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: float = 90.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> ProviderSmokeResult:
    base_url = base_url.rstrip("/")
    if not base_url.startswith("https://"):
        raise ProviderSmokeError("provider smoke requires an HTTPS base_url")
    if not api_key:
        raise ProviderSmokeError("provider API credential is empty")
    if not model:
        raise ProviderSmokeError("provider model is empty")

    endpoint = base_url + "/chat/completions"
    started = time.perf_counter()
    prompt_tokens = completion_tokens = total_tokens = 0

    text_payload = _post_json(
        endpoint,
        api_key,
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Provider smoke test. Reply with exactly TEXT_OK and nothing else."
                    ),
                }
            ],
            "temperature": 0,
            "max_tokens": 16,
        },
        timeout=timeout,
        opener=opener,
    )
    text_response = _extract_content(text_payload)
    p, c, t = _usage(text_payload)
    prompt_tokens += p
    completion_tokens += c
    total_tokens += t
    text_ok = "TEXT_OK" in text_response.upper()
    if not text_ok:
        raise ProviderSmokeError(
            "text smoke response did not contain the expected TEXT_OK marker"
        )

    try:
        vision_payload = _post_json(
            endpoint,
            api_key,
            {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": magenta_png_data_url()},
                            },
                            {
                                "type": "text",
                                "text": (
                                    "What is the dominant color of the attached image? "
                                    "Reply with exactly MAGENTA and nothing else."
                                ),
                            },
                        ],
                    }
                ],
                "temperature": 0,
                "max_tokens": 16,
            },
            timeout=timeout,
            opener=opener,
        )
        except ProviderSmokeError as exc:
        raise ProviderSmokeError(str(exc), provider_calls=1, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens, stage="vision") from exc
    vision_response = _extract_content(vision_payload)
    p, c, t = _usage(vision_payload)
    prompt_tokens += p
    completion_tokens += c
    total_tokens += t
    vision_ok = "MAGENTA" in vision_response.upper()
    if not vision_ok:
        raise ProviderSmokeError(
            "vision smoke response did not contain the expected MAGENTA marker"
        )

    return ProviderSmokeResult(
        model=model,
        base_url=base_url,
        text_ok=text_ok,
        vision_ok=vision_ok,
        provider_calls=2,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_seconds=time.perf_counter() - started,
        text_response=text_response[:120],
        vision_response=vision_response[:120],
    )
