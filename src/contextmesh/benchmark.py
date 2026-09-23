from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from .models import ContextBlock
from .reader import CorpusReader
from .runtime import ProgressiveEvaluator


class DirectScoringJudge(Protocol):
    def score_full(self, question: str, answer: str, blocks: list[ContextBlock]) -> tuple[float, str]: ...


class ScorePreservationResult(BaseModel):
    corpus_id: str
    direct_score: float
    progressive_score: float
    absolute_drift: float
    tolerance: float
    passed: bool
    coverage: float
    total_blocks: int
    total_chars: int
    rationale_direct: str
    rationale_progressive: str


@dataclass
class ScorePreservationBenchmark:
    """Compare progressive execution with a direct full-context gold path.

    The direct path is intentionally restricted to corpora small enough to fit in one
    request. Those corpora become calibration fixtures for the large-context runtime.
    """

    evaluator: ProgressiveEvaluator
    judge: DirectScoringJudge
    max_direct_chars: int = 250_000
    tolerance: float = 1.0

    def run(self, corpus_id: str, question: str, answer: str) -> ScorePreservationResult:
        reader = CorpusReader(self.evaluator.store, corpus_id)
        blocks = [reader.read(x) for x in reader.required_ids]
        total_chars = sum(len(b.text) for b in blocks)
        if total_chars > self.max_direct_chars:
            raise ValueError(
                f"direct baseline disabled: corpus has {total_chars} chars > max_direct_chars={self.max_direct_chars}"
            )
        direct_score, direct_rationale = self.judge.score_full(question, answer, blocks)
        progressive = self.evaluator.evaluate(corpus_id, question, answer)
        if not progressive.complete or progressive.score is None:
            raise RuntimeError("progressive benchmark run did not complete full coverage")
        drift = abs(float(direct_score) - float(progressive.score))
        return ScorePreservationResult(
            corpus_id=corpus_id,
            direct_score=float(direct_score),
            progressive_score=float(progressive.score),
            absolute_drift=drift,
            tolerance=self.tolerance,
            passed=drift <= self.tolerance,
            coverage=progressive.coverage,
            total_blocks=progressive.total_blocks,
            total_chars=total_chars,
            rationale_direct=direct_rationale,
            rationale_progressive=progressive.rationale,
        )
