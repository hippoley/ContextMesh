from __future__ import annotations

import os
import urllib.request
from collections import defaultdict

from .models import RuntimeTelemetry


def _fetch_text(url: str, timeout: float = 2.5) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_prometheus(text: str) -> dict[str, float]:
    """Parse scalar Prometheus samples, summing samples with the same metric name."""
    values: dict[str, float] = defaultdict(float)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            left, value = line.rsplit(None, 1)
            name = left.split("{", 1)[0]
            values[name] += float(value)
        except Exception:
            continue
    return dict(values)


def _first(m: dict[str, float], *names: str) -> float | None:
    for n in names:
        if n in m:
            return m[n]
    return None


def collect_runtime_telemetry(
    vllm_url: str | None = None,
    lmcache_url: str | None = None,
) -> RuntimeTelemetry:
    vllm_url = vllm_url or os.getenv("CONTEXTMESH_VLLM_METRICS_URL")
    lmcache_url = lmcache_url or os.getenv("CONTEXTMESH_LMCACHE_METRICS_URL")
    merged: dict[str, float] = {}
    sources: list[str] = []
    errors: list[str] = []

    for label, url in (("vllm", vllm_url), ("lmcache", lmcache_url)):
        if not url:
            continue
        try:
            merged.update(parse_prometheus(_fetch_text(url)))
            sources.append(label)
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")

    lm_requested = _first(
        merged,
        "lmcache:num_requested_tokens",
        "lmcache_num_requested_tokens",
        "lmcache_mp_lookup_requested_tokens_total",
        "lmcache_mp_lookup_requested_total",
    )
    lm_hit = _first(
        merged,
        "lmcache:num_hit_tokens",
        "lmcache_num_hit_tokens",
        "lmcache_mp_lookup_hit_tokens_total",
        "lmcache_mp_lookup_hit_total",
    )
    explicit_lm_rate = _first(merged, "lmcache:retrieve_hit_rate", "lmcache_retrieve_hit_rate", "lmcache:lookup_hit_rate")
    lm_rate = explicit_lm_rate
    if lm_rate is None and lm_requested and lm_requested > 0 and lm_hit is not None:
        lm_rate = lm_hit / lm_requested

    prefix_q = _first(merged, "vllm:prefix_cache_queries", "vllm_prefix_cache_queries_total", "vllm_prefix_cache_queries")
    prefix_h = _first(merged, "vllm:prefix_cache_hits", "vllm_prefix_cache_hits_total", "vllm_prefix_cache_hits")
    prefix_rate = prefix_h / prefix_q if prefix_q and prefix_q > 0 and prefix_h is not None else None

    ttft_sum = _first(merged, "vllm:time_to_first_token_seconds_sum", "vllm_time_to_first_token_seconds_sum")
    ttft_count = _first(merged, "vllm:time_to_first_token_seconds_count", "vllm_time_to_first_token_seconds_count")
    avg_ttft = ttft_sum / ttft_count if ttft_sum is not None and ttft_count else None

    return RuntimeTelemetry(
        source="+".join(sources) if sources else "unconfigured",
        lmcache_hit_rate=lm_rate,
        lmcache_requested_tokens=lm_requested,
        lmcache_hit_tokens=lm_hit,
        vllm_prefix_hit_rate=prefix_rate,
        kv_cache_usage=_first(merged, "vllm:kv_cache_usage_perc", "vllm_kv_cache_usage_perc"),
        prompt_tokens_total=_first(merged, "vllm:prompt_tokens_total", "vllm_prompt_tokens_total", "vllm:prompt_tokens", "vllm_prompt_tokens"),
        generation_tokens_total=_first(merged, "vllm:generation_tokens_total", "vllm_generation_tokens_total", "vllm:generation_tokens", "vllm_generation_tokens"),
        avg_ttft_seconds=avg_ttft,
        raw_metrics_available=bool(merged),
        error="; ".join(errors) if errors else None,
    )
