from __future__ import annotations

import base64
import json
import mimetypes
import urllib.request
import time
from pathlib import Path
from typing import Any

from .evidence import render_typed_evidence
from .models import ContextBlock, EvaluationState, Modality, UsageMetrics


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    return str(value or "")

def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw).strip()
    candidates = [text]
    if "```" in text:
        stripped = text.replace("```json", "```").replace("```JSON", "```")
        pieces = stripped.split("```")
        candidates.extend(x.strip() for i, x in enumerate(pieces) if i % 2 == 1 and x.strip())
    first, last = text.find("{"), text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


class HeuristicJudge:
    """Offline smoke-test judge. Not intended for production quality scoring."""

    def can_inspect(self, block: ContextBlock) -> bool:
        # The offline lexical judge has no native vision/audio/video capability.
        # It may inspect non-text modalities only when a parser supplied a textual
        # representation (caption/transcript/description).
        if block.modality in {Modality.TEXT, Modality.TABLE}:
            return True
        return bool((block.text or "").strip())

    def inspect(self, question: str, answer: str, block: ContextBlock, notes: list[str]) -> tuple[str, bool]:
        terms = {x.lower().strip(".,?!:;()[]{}") for x in question.split() if len(x) > 2}
        text = block.text.lower()
        hits = sorted(t for t in terms if t and t in text)
        relevant = bool(hits)
        note = (
            f"{block.id} [{block.modality.value}]: matched={','.join(hits[:8])}"
            if relevant
            else f"{block.id} [{block.modality.value}]: inspected; no lexical match"
        )
        return note, relevant

    def reduce_notes(self, question: str, answer: str, notes: list[str], level: int) -> str:
        # Deterministic bounded state used in offline tests. Preserve block identifiers
        # and whether each inspection found a match, while avoiding unbounded growth.
        matched = [n for n in notes if "matched=" in n]
        ids = [n.split(" ", 1)[0] for n in notes]
        return (
            f"L{level} reduction: inspected={len(notes)} relevant={len(matched)} "
            f"blocks={','.join(ids[:64])}"
        )

    def finalize(self, state: EvaluationState) -> tuple[float, str]:
        score = min(100.0, 50.0 + len(state.evidence) * 5.0)
        return score, (
            f"Offline PoC score using {len(state.evidence)} evidence blocks after exhaustive traversal; "
            f"final model context contains {len(state.model_context_notes())} reduced items."
        )


    def usage_snapshot(self) -> UsageMetrics:
        return UsageMetrics()

    def score_full(self, question: str, answer: str, blocks: list[ContextBlock]) -> tuple[float, str]:
        terms = {x.lower().strip(".,?!:;()[]{}") for x in question.split() if len(x) > 2}
        relevant = 0
        for block in blocks:
            text = block.text.lower()
            if any(t and t in text for t in terms):
                relevant += 1
        score = min(100.0, 50.0 + relevant * 5.0)
        return score, f"Direct full-context heuristic baseline over {len(blocks)} blocks."


class OpenAICompatibleJudge:
    supports_neighbor_context = True
    """Cloud/local judge for OpenAI-compatible Chat Completions endpoints.

    Text/table/audio/video blocks are represented as structured text. Direct image
    assets can be attached as data URLs for endpoints/models that support vision.
    Embedded images without an independently addressable image file fall back to
    Docling caption/description text, preserving portability across providers.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "EMPTY",
        *,
        enable_images: bool = True,
        max_inline_image_bytes: int = 5_000_000,
        route_id: str | None = None,
        input_cost_per_million: float = 0.0,
        output_cost_per_million: float = 0.0,
        capabilities: list[str] | set[str] | None = None,
        max_context_tokens: int | None = None,
        reserve_output_tokens: int = 1200,
        chars_per_token_estimate: float = 3.2,
        request_timeout_seconds: float = 120.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.enable_images = enable_images
        self.max_inline_image_bytes = max_inline_image_bytes
        self.route_id = route_id
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self.capabilities = set(capabilities or ["text", "table", "vision"])
        self.max_context_tokens = max_context_tokens
        self.reserve_output_tokens = max(256, int(reserve_output_tokens))
        self.chars_per_token_estimate = max(1.5, float(chars_per_token_estimate))
        self.request_timeout_seconds = max(5.0, float(request_timeout_seconds))
        self._usage = UsageMetrics(route_id=route_id)

    def _max_text_chars(self, question: str = "", answer: str = "", *, overhead_chars: int = 5000) -> int | None:
        if not self.max_context_tokens:
            return None
        usable_tokens = max(512, self.max_context_tokens - self.reserve_output_tokens)
        total_chars = int(usable_tokens * self.chars_per_token_estimate)
        return max(1000, total_chars - len(question) - len(answer) - overhead_chars)

    @staticmethod
    def _split_text(text: str, limit: int, overlap: int = 600) -> list[str]:
        if len(text) <= limit:
            return [text]
        out: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + limit)
            if end < len(text):
                # Prefer a natural boundary near the end without sacrificing coverage.
                floor = max(start + limit // 2, start)
                cut = max(text.rfind("\n", floor, end), text.rfind(". ", floor, end))
                if cut > floor:
                    end = cut + 1
            out.append(text[start:end])
            if end >= len(text):
                break
            start = max(start + 1, end - min(overlap, limit // 5))
        return out

    def preflight_block(self, question: str, answer: str, block: ContextBlock) -> str | None:
        if self.max_context_tokens:
            base_chars = len(question) + len(answer) + 5000
            capacity = int(max(512, self.max_context_tokens - self.reserve_output_tokens) * self.chars_per_token_estimate)
            if base_chars >= capacity:
                return (
                    f"question + candidate answer leave no safe context budget for route {self.route_id or self.model}; "
                    f"max_context_tokens={self.max_context_tokens}"
                )
        return None

    def _chat(self, messages: list[dict[str, Any]]) -> str:
        body = json.dumps({"model": self.model, "messages": messages, "temperature": 0}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.request_timeout_seconds) as resp:
            data = json.loads(resp.read().decode())
        self._usage.requests += 1
        self._usage.latency_seconds += time.perf_counter() - started
        usage = data.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens") or usage.get("cached_prompt_tokens") or 0)
        self._usage.prompt_tokens += prompt
        self._usage.completion_tokens += completion
        self._usage.cached_prompt_tokens += cached
        self._usage.estimated_cost_usd = (
            self._usage.prompt_tokens * self.input_cost_per_million / 1_000_000
            + self._usage.completion_tokens * self.output_cost_per_million / 1_000_000
        )
        return _content_text(data["choices"][0]["message"].get("content"))

    def usage_snapshot(self) -> UsageMetrics:
        return self._usage.model_copy(deep=True)

    def health_check(self) -> dict[str, Any]:
        started = time.perf_counter()
        raw = self._chat([{
            "role": "user",
            "content": [{"type": "text", "text": "Reply with exactly OK."}],
        }])
        return {
            "ok": bool(str(raw).strip()),
            "latency_seconds": time.perf_counter() - started,
            "response_preview": str(raw).strip()[:120],
            "model": self.model,
            "route_id": self.route_id,
        }


    def _direct_image_data_url(self, block: ContextBlock) -> str | None:
        if not self.enable_images or block.modality != Modality.IMAGE:
            return None
        media_path = block.metadata.get("media_path") or block.source.path
        p = Path(str(media_path))
        if not p.is_file() or p.stat().st_size > self.max_inline_image_bytes:
            return None
        mime = block.metadata.get("media_mime")
        if not mime:
            mime, _ = mimetypes.guess_type(p.name)
        if not mime or not str(mime).startswith("image/"):
            return None
        raw = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{raw}"

    def can_inspect(self, block: ContextBlock) -> bool:
        if block.modality == Modality.TEXT:
            return "text" in self.capabilities
        if block.modality == Modality.TABLE:
            return "table" in self.capabilities or "text" in self.capabilities
        if block.modality == Modality.IMAGE:
            # A parser-provided caption/description can be inspected by a text route;
            # otherwise a real visual payload requires vision capability.
            if (block.text or "").strip() and "text" in self.capabilities:
                return True
            return "vision" in self.capabilities and bool(self._direct_image_data_url(block))
        # Chat-Completions-compatible adapters are not assumed to support native
        # audio/video payloads. A parser-provided transcript/description is safe.
        if block.modality == Modality.AUDIO:
            return bool((block.text or "").strip()) or self._direct_audio_payload(block) is not None
        if block.modality == Modality.VIDEO:
            # The generic OpenAI-compatible Chat Completions adapter has no portable
            # native video schema. Require a textual representation until a provider-
            # specific adapter is installed.
            return bool((block.text or "").strip())
        return False

    def _direct_audio_payload(self, block: ContextBlock) -> dict[str, Any] | None:
        if block.modality != Modality.AUDIO or "audio" not in self.capabilities:
            return None
        media_path = Path(str(block.metadata.get("media_path") or block.source.path))
        if not media_path.is_file() or media_path.stat().st_size > self.max_inline_image_bytes * 4:
            return None
        ext = media_path.suffix.lower().lstrip(".")
        if ext not in {"wav", "mp3"}:
            return None
        raw = base64.b64encode(media_path.read_bytes()).decode("ascii")
        return {"type": "input_audio", "input_audio": {"data": raw, "format": ext}}

    def build_block_content(self, question: str, answer: str, block: ContextBlock, *, text_override: str | None = None, slice_label: str | None = None) -> list[dict[str, Any]]:
        locator = json.dumps(block.source.locator, ensure_ascii=False)
        instruction = (
            "You are one worker in a full-coverage evaluation. Inspect this block; do not assume other blocks are absent. "
            "Return strict JSON with keys relevant:boolean and note:string. Preserve contradictions, exceptions, numbers, dates, "
            "and evidence that can change the evaluation.\n\n"
            f"QUESTION:\n{question}\n\nCANDIDATE ANSWER:\n{answer}\n\n"
            f"BLOCK ID: {block.id}\nMODALITY: {block.modality.value}\nSOURCE: {block.source.path}\nLOCATOR: {locator}\n"
            f"SLICE: {slice_label or 'full'}\n\n"
            f"EXTRACTED/STRUCTURED CONTENT:\n{text_override if text_override is not None else block.text}"
            "\n\nIf PREVIOUS/NEXT CONTEXT markers are present, use them only to resolve boundaries; the CURRENT block remains the coverage unit."
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
        image_url = self._direct_image_data_url(block)
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        if "vision" in self.capabilities:
            for media_path in block.metadata.get("contextmesh_related_media_paths", [])[:4]:
                p = Path(str(media_path))
                if not p.is_file() or p.stat().st_size > self.max_inline_image_bytes:
                    continue
                mime, _ = mimetypes.guess_type(p.name)
                if not mime or not mime.startswith("image/"):
                    continue
                raw = base64.b64encode(p.read_bytes()).decode("ascii")
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{raw}"}})
        audio_payload = self._direct_audio_payload(block)
        if audio_payload:
            content.append(audio_payload)
        return content

    def inspect(self, question: str, answer: str, block: ContextBlock, notes: list[str]) -> tuple[str, bool]:
        limit = self._max_text_chars(question, answer)
        parts = self._split_text(block.text or "", limit) if limit else [block.text or ""]
        findings: list[str] = []
        relevant_any = False
        for i, part in enumerate(parts, 1):
            raw = self._chat([{
                "role": "user",
                "content": self.build_block_content(
                    question, answer, block, text_override=part,
                    slice_label=f"{i}/{len(parts)}" if len(parts) > 1 else "full",
                ),
            }])
            obj = _parse_json_object(raw)
            if obj is not None:
                findings.append(str(obj.get("note", raw)))
                relevant_any = relevant_any or bool(obj.get("relevant", True))
            else:
                findings.append(raw)
                relevant_any = True
        if len(findings) == 1:
            return findings[0], relevant_any
        # All slices were inspected; condense only after exhaustive per-block coverage.
        combined = self.reduce_notes(question, answer, [f"{block.id} slice {i+1}/{len(findings)}: {x}" for i, x in enumerate(findings)], 0)
        return f"{block.id} route-aware slices={len(findings)}; {combined}", relevant_any

    def reduce_notes(self, question: str, answer: str, notes: list[str], level: int) -> str:
        limit = self._max_text_chars(question, answer, overhead_chars=7000)
        if limit and sum(len(x) + 1 for x in notes) > limit:
            groups: list[list[str]] = []
            current: list[str] = []
            size = 0
            for note in notes:
                if current and size + len(note) + 1 > limit:
                    groups.append(current)
                    current, size = [], 0
                current.append(note)
                size += len(note) + 1
            if current:
                groups.append(current)
            reduced = [self.reduce_notes(question, answer, g, level + 1) for g in groups]
            if len(reduced) == 1:
                return reduced[0]
            return self.reduce_notes(question, answer, reduced, level + 1)
        prompt = (
            "Compress these inspection findings into a score-preserving evaluation state. Do not discard contradictions, "
            "exceptions, dates, numbers, or block identifiers. Do not decide the final score yet. Return concise plain text.\n\n"
            f"QUESTION:\n{question}\n\nANSWER:\n{answer}\n\nREDUCTION LEVEL: {level}\n\n"
            "FINDINGS:\n" + "\n".join(notes)
        )
        return self._chat([{"role": "user", "content": prompt}])

    def finalize(self, state: EvaluationState) -> tuple[float, str]:
        notes = state.model_context_notes()
        limit = self._max_text_chars(state.question, state.answer, overhead_chars=7000)
        if limit and sum(len(x) + 1 for x in notes) > limit:
            notes = [self.reduce_notes(state.question, state.answer, notes, 99)]
        joined = "\n".join(notes)
        typed_budget = max(4_000, min(32_000, (limit // 3) if limit else 32_000))
        typed = render_typed_evidence(state.evidence, max_chars=typed_budget)
        prompt = (
            "Produce strict JSON {score:number,rationale:string}. Score the candidate answer against the question using the "
            "complete, hierarchically reduced inspection state below. Full corpus coverage has already been enforced by the runtime. "
            "Typed evidence is a source-linked preservation channel for numbers, dates, exceptions, contradictions and requirements; "
            "treat it as authoritative evidence metadata, not as a replacement for the reduced inspection state.\n\n"
            f"QUESTION:\n{state.question}\n\nANSWER:\n{state.answer}\n\nREDUCED INSPECTION STATE:\n{joined}"
            f"\n\nTYPED EVIDENCE STATE:\n{typed or '(none)'}"
        )
        raw = self._chat([{"role": "user", "content": prompt}])
        obj = _parse_json_object(raw)
        if obj is not None and "score" in obj:
            return float(obj["score"]), str(obj.get("rationale", ""))
        raise ValueError(f"judge final response was not parseable JSON: {raw[:500]}")

    def score_full(self, question: str, answer: str, blocks: list[ContextBlock]) -> tuple[float, str]:
        """Direct single-request baseline for calibration corpora that fit one context.

        This path is intentionally not used for arbitrarily large corpora; it exists to
        quantify score drift against progressive execution on a direct-fit benchmark set.
        """
        content: list[dict[str, Any]] = [{
            "type": "text",
            "text": (
                "Produce strict JSON {score:number,rationale:string}. Evaluate the candidate answer against the question using "
                "ALL source blocks below in this single request. Preserve contradictions, exceptions, numbers and dates.\n\n"
                f"QUESTION:\n{question}\n\nANSWER:\n{answer}\n\nFULL CORPUS FOLLOWS.\n"
            ),
        }]
        for block in blocks:
            locator = json.dumps(block.source.locator, ensure_ascii=False)
            content.append({
                "type": "text",
                "text": f"\n--- BLOCK {block.id} [{block.modality.value}] {block.source.path} {locator} ---\n{block.text}",
            })
            image_url = self._direct_image_data_url(block)
            if image_url:
                content.append({"type": "image_url", "image_url": {"url": image_url}})
        raw = self._chat([{"role": "user", "content": content}])
        obj = _parse_json_object(raw)
        if obj is not None and "score" in obj:
            return float(obj["score"]), str(obj.get("rationale", ""))
        raise ValueError(f"judge full-context response was not parseable JSON: {raw[:500]}")
