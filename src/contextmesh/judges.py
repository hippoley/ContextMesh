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
from .semantics import DecisionBundle, render_decision_bundle_checked, shard_decision_bundle
from .token_budget import TextTokenBudget, TokenBudgetExceeded, load_token_counter


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
        chars_per_token_estimate: float = 1.0,
        tokenizer_spec: str | None = None,
        token_budget_safety_factor: float = 0.90,
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
        self.chars_per_token_estimate = max(0.25, float(chars_per_token_estimate))
        self.tokenizer_spec = tokenizer_spec
        self.token_budget_safety_factor = max(0.1, min(1.0, float(token_budget_safety_factor)))
        self.token_budget = TextTokenBudget(
            max_context_tokens=self.max_context_tokens,
            reserve_output_tokens=self.reserve_output_tokens,
            safety_factor=self.token_budget_safety_factor,
            chars_per_token_estimate=self.chars_per_token_estimate,
            counter_spec=load_token_counter(tokenizer_spec, model=model),
        )
        self.request_timeout_seconds = max(5.0, float(request_timeout_seconds))
        self._usage = UsageMetrics(route_id=route_id)

    def _available_source_tokens(
        self,
        question: str = "",
        answer: str = "",
        *,
        prompt_overhead_tokens: int = 2200,
    ) -> int | None:
        return self.token_budget.available_text_tokens(
            question=question,
            answer=answer,
            prompt_overhead_tokens=prompt_overhead_tokens,
        )

    def _block_source_budget_tokens(
        self,
        question: str,
        answer: str,
        block: ContextBlock,
    ) -> int | None:
        budget = self.token_budget.input_budget_tokens()
        if budget is None:
            return None
        fixed_content = self.build_block_content(
            question,
            answer,
            block,
            text_override="",
            slice_label="budget-probe",
        )
        fixed_tokens, _ = self.token_budget.count_messages([
            {"role": "user", "content": fixed_content}
        ])
        return max(0, budget - fixed_tokens)

    def token_budget_status(self) -> dict[str, Any]:
        return {
            "mode": self.token_budget.mode,
            "exact_text": self.token_budget.exact,
            "tokenizer_spec": self.tokenizer_spec,
            "max_context_tokens": self.max_context_tokens,
            "reserve_output_tokens": self.reserve_output_tokens,
            "safety_factor": self.token_budget_safety_factor,
            "usable_input_tokens": self.token_budget.input_budget_tokens(),
            "chars_per_token_estimate": self.chars_per_token_estimate,
        }

    def preflight_block(self, question: str, answer: str, block: ContextBlock) -> str | None:
        available = self._block_source_budget_tokens(question, answer, block)
        if available is not None and available < 32:
            return (
                f"constructed inspection prompt leaves no safe source token budget for route "
                f"{self.route_id or self.model}; max_context_tokens={self.max_context_tokens}, "
                f"usable_input_tokens={self.token_budget.input_budget_tokens()}, "
                f"remaining_source_tokens={available}, budget_mode={self.token_budget.mode}"
            )
        return None

    def _chat(self, messages: list[dict[str, Any]]) -> str:
        self.token_budget.assert_messages(messages)
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
        available = self._block_source_budget_tokens(question, answer, block)
        parts = (
            self.token_budget.split_text(
                block.text or "",
                budget_tokens=available,
                overlap_chars=600,
            )
            if available is not None
            else [block.text or ""]
        )
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
        limit = self._available_source_tokens(
            question,
            answer,
            prompt_overhead_tokens=2600,
        )
        total_note_tokens = sum(self.token_budget.count(x) + 1 for x in notes)
        if limit is not None and total_note_tokens > limit:
            groups: list[list[str]] = []
            current: list[str] = []
            size = 0
            for note in notes:
                note_tokens = self.token_budget.count(note) + 1
                if note_tokens > limit:
                    # Legacy explanation text is allowed to split, but the typed
                    # preservation channel remains source-linked and untouched.
                    pieces = self.token_budget.split_text(
                        note,
                        budget_tokens=limit,
                        overlap_chars=0,
                    )
                else:
                    pieces = [note]
                for piece in pieces:
                    piece_tokens = self.token_budget.count(piece) + 1
                    if current and size + piece_tokens > limit:
                        groups.append(current)
                        current, size = [], 0
                    current.append(piece)
                    size += piece_tokens
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

    def preflight_finalize(self, state: EvaluationState) -> str | None:
        if state.decision_bundle is None:
            return None
        available = self._available_source_tokens(
            state.question,
            state.answer,
            prompt_overhead_tokens=3200,
        )
        if available is None:
            return None

        bundle_token_budget = max(512, available // 2)
        bundle = DecisionBundle.model_validate(state.decision_bundle)
        rendered_full = render_decision_bundle_checked(bundle, max_chars=100_000_000)
        required_tokens = self.token_budget.count(rendered_full.text)
        if required_tokens <= bundle_token_budget:
            return None

        # Shards are a transport representation only. Use a conservative char budget
        # so each shard will also fit under the token gate for the fallback path.
        shard_chars = max(
            1024,
            int(bundle_token_budget * min(1.0, self.chars_per_token_estimate)),
        )
        shards = shard_decision_bundle(bundle, max_chars=shard_chars)
        return (
            "DecisionBundle exceeds the final model-facing token budget; refusing lossy "
            f"finalization. The complete decision state can be transported losslessly "
            f"as {shards.shard_count} shard(s), but no cross-shard verdict aggregation "
            f"contract is assumed yet. required_tokens={required_tokens}, "
            f"bundle_token_budget={bundle_token_budget}, budget_mode={self.token_budget.mode}"
        )

    def finalize(self, state: EvaluationState) -> tuple[float, str]:
        notes = state.model_context_notes()
        available = self._available_source_tokens(
            state.question,
            state.answer,
            prompt_overhead_tokens=3200,
        )
        if available is not None:
            note_tokens = sum(self.token_budget.count(x) + 1 for x in notes)
            if note_tokens > max(512, available // 3):
                notes = [self.reduce_notes(state.question, state.answer, notes, 99)]
        joined = "\n".join(notes)

        # Legacy typed evidence is a cross-check only. Keep its textual render
        # conservative; the final request gate remains authoritative.
        typed_budget_chars = 16_000 if available is not None else 32_000
        typed = render_typed_evidence(state.evidence, max_chars=typed_budget_chars)

        if state.decision_bundle is not None:
            bundle = DecisionBundle.model_validate(state.decision_bundle)
            rendered_bundle = render_decision_bundle_checked(bundle, max_chars=100_000_000)
            if available is not None:
                bundle_tokens = self.token_budget.count(rendered_bundle.text)
                if bundle_tokens > max(512, available // 2):
                    raise RuntimeError(
                        "refusing to judge an incomplete token-budgeted DecisionBundle: "
                        f"required_tokens={bundle_tokens} "
                        f"bundle_token_budget={max(512, available // 2)}"
                    )
            decision_state = rendered_bundle.text
        else:
            decision_state = "(no structured DecisionBundle available)"

        prompt = (
            "Produce strict JSON {score:number,rationale:string}. Score the candidate answer against the question. "
            "Full corpus coverage and runtime execution contracts have already been enforced before this call. "
            "The DECISION BUNDLE is the primary preservation channel: exceptions, contradictions, requirements and unresolved "
            "authority must not be ignored merely because a free-form reduction is shorter or smoother. "
            "The reduced inspection state is an explanatory/context channel. Legacy typed evidence is included as a source-linked "
            "cross-check for numbers, dates and critical atoms.\n\n"
            f"QUESTION:\n{state.question}\n\nANSWER:\n{state.answer}"
            f"\n\nDECISION BUNDLE:\n{decision_state}"
            f"\n\nREDUCED INSPECTION STATE:\n{joined}"
            f"\n\nLEGACY TYPED EVIDENCE:\n{typed or '(none)'}"
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
