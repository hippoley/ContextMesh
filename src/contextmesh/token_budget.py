from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


class TokenBudgetExceeded(ValueError):
    pass


TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class TokenCounterSpec:
    counter: TokenCounter
    label: str
    exact: bool = True


def load_token_counter(spec: str | None, *, model: str) -> TokenCounterSpec | None:
    """Load an optional route-declared tokenizer.

    Supported specs:
      - tiktoken:model       -> tiktoken.encoding_for_model(model)
      - tiktoken:<encoding>  -> tiktoken.get_encoding(<encoding>)

    No tokenizer is guessed for non-OpenAI model families.
    """
    if not spec:
        return None
    if not spec.startswith("tiktoken:"):
        raise ValueError(f"unsupported tokenizer spec: {spec}")

    try:
        import tiktoken
    except ImportError as exc:
        raise ValueError(
            "tokenizer_spec requires the optional tokenizers extra: "
            "pip install -e '.[tokenizers]'"
        ) from exc

    target = spec.split(":", 1)[1].strip()
    if not target:
        raise ValueError("tiktoken tokenizer spec requires model or encoding name")

    if target == "model":
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError as exc:
            raise ValueError(
                f"tiktoken has no known encoding for model {model!r}; "
                "set tokenizer_spec to an explicit tiktoken:<encoding>"
            ) from exc
    else:
        try:
            encoding = tiktoken.get_encoding(target)
        except ValueError as exc:
            raise ValueError(f"unknown tiktoken encoding: {target}") from exc

    def count(text: str) -> int:
        return len(encoding.encode(text or "", disallowed_special=()))

    return TokenCounterSpec(
        counter=count,
        label=f"tiktoken:{encoding.name}",
        exact=True,
    )


@dataclass
class TextTokenBudget:
    max_context_tokens: int | None
    reserve_output_tokens: int = 1200
    safety_factor: float = 0.90
    chars_per_token_estimate: float = 1.0
    counter_spec: TokenCounterSpec | None = None

    @property
    def mode(self) -> str:
        return self.counter_spec.label if self.counter_spec else "conservative-char-estimate"

    @property
    def exact(self) -> bool:
        return bool(self.counter_spec and self.counter_spec.exact)

    def count(self, text: str) -> int:
        if self.counter_spec:
            return max(0, int(self.counter_spec.counter(text or "")))
        return int(math.ceil(len(text or "") / max(0.25, self.chars_per_token_estimate)))

    def input_budget_tokens(self) -> int | None:
        if not self.max_context_tokens:
            return None
        raw = max(0, int(self.max_context_tokens) - int(self.reserve_output_tokens))
        return max(0, int(raw * max(0.1, min(1.0, self.safety_factor))))

    def available_text_tokens(
        self,
        *,
        question: str = "",
        answer: str = "",
        prompt_overhead_tokens: int = 1600,
    ) -> int | None:
        budget = self.input_budget_tokens()
        if budget is None:
            return None
        used = self.count(question) + self.count(answer) + max(0, prompt_overhead_tokens)
        return max(0, budget - used)

    def assert_text_request(
        self,
        text: str,
        *,
        media_items: int = 0,
        media_reserve_tokens: int = 1024,
    ) -> int:
        tokens = self.count(text)
        budget = self.input_budget_tokens()
        if budget is None:
            return tokens
        effective_budget = max(0, budget - max(0, media_items) * media_reserve_tokens)
        if tokens > effective_budget:
            raise TokenBudgetExceeded(
                f"model-facing request exceeds ContextMesh token budget: "
                f"estimated_or_exact_tokens={tokens}, budget={effective_budget}, "
                f"mode={self.mode}, media_items={media_items}"
            )
        return tokens

    def split_text(
        self,
        text: str,
        *,
        budget_tokens: int,
        overlap_chars: int = 600,
    ) -> list[str]:
        """Split text so every emitted part fits the configured token measure."""
        if budget_tokens < 1:
            raise TokenBudgetExceeded("no model-facing token budget remains for source text")
        if self.count(text) <= budget_tokens:
            return [text]

        out: list[str] = []
        start = 0
        length = len(text)
        while start < length:
            lo = start + 1
            hi = length
            best = start

            while lo <= hi:
                mid = (lo + hi) // 2
                if self.count(text[start:mid]) <= budget_tokens:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1

            if best <= start:
                raise TokenBudgetExceeded(
                    f"cannot fit even one character into token budget={budget_tokens} "
                    f"using {self.mode}"
                )

            end = best
            if end < length:
                floor = max(start + 1, start + (end - start) // 2)
                cut = max(
                    text.rfind("\n", floor, end),
                    text.rfind(". ", floor, end),
                    text.rfind("。", floor, end),
                    text.rfind("；", floor, end),
                )
                if cut > floor and self.count(text[start : cut + 1]) <= budget_tokens:
                    end = cut + 1

            part = text[start:end]
            if self.count(part) > budget_tokens:
                raise RuntimeError("internal token splitter emitted an oversized part")
            out.append(part)

            if end >= length:
                break
            start = max(start + 1, end - min(overlap_chars, max(1, (end - start) // 5)))

        return out
