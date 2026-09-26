from __future__ import annotations

import hashlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Protocol

from .diagnostics import EvidenceStage
from .evidence import evidence_kind_counts, extract_evidence_atoms
from .models import EvaluationCheckpoint, EvaluationResult, EvaluationState, Evidence, ReductionNode
from .reader import CorpusReader
from .semantics import CoverageSnapshot, ExecutionContract, TransitionAction, TransitionLedger, TransitionReceipt
from .store import FileContextStore


class Judge(Protocol):
    def inspect(self, question: str, answer: str, block, notes: list[str]) -> tuple[str, bool]: ...
    def finalize(self, state: EvaluationState) -> tuple[float, str]: ...


@dataclass
class CoverageController:
    expected: set[str]
    visited: set[str]

    @property
    def coverage(self) -> float:
        if not self.expected:
            return 1.0
        return len(self.expected & self.visited) / len(self.expected)

    @property
    def complete(self) -> bool:
        return self.expected.issubset(self.visited)

    @property
    def missing(self) -> set[str]:
        return self.expected - self.visited

    def assert_complete(self) -> None:
        if not self.complete:
            raise RuntimeError(
                f"full-coverage contract violated: {len(self.expected & self.visited)}/{len(self.expected)} required blocks visited; "
                f"missing={len(self.missing)}"
            )


@dataclass(frozen=True)
class _InspectionOutcome:
    block_id: str
    note: str | None
    relevant: bool
    attempts: int
    error: str | None = None


class ProgressiveEvaluator:
    """Full-coverage external-context evaluator with bounded model-facing state.

    v0.4 adds deterministic parallel inspection and retryable failures. Ranking may
    prioritize blocks but never filters them. A failed block remains unvisited, so no
    final score can be emitted until it succeeds in this or a resumed run.
    """

    def __init__(
        self,
        store: FileContextStore,
        judge: Judge,
        *,
        reduction_batch_size: int = 32,
        max_workers: int = 1,
        retry_attempts: int = 1,
        retry_backoff_seconds: float = 0.0,
        execution_batch_size: int | None = None,
        progress_callback: Callable[[dict], None] | None = None,
        neighbor_context_chars: int = 800,
        cancellation_check: Callable[[str, str], bool] | None = None,
    ):
        if reduction_batch_size < 2:
            raise ValueError("reduction_batch_size must be >= 2")
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be >= 1")
        self.store = store
        self.judge = judge
        self.reduction_batch_size = reduction_batch_size
        self.max_workers = max_workers
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.execution_batch_size = execution_batch_size or max(1, max_workers * 2)
        self.progress_callback = progress_callback
        self.neighbor_context_chars = max(0, neighbor_context_chars)
        self.cancellation_check = cancellation_check

    @property
    def execution_mode(self) -> str:
        return "parallel" if self.max_workers > 1 else "sequential"

    def _ordered_ids(self, reader: CorpusReader, question: str, order: list[str] | None) -> list[str]:
        expected = set(reader.required_ids)
        preferred = order if order is not None else reader.lexical_order(question)
        normalized: list[str] = []
        seen: set[str] = set()
        for block_id in preferred:
            if block_id in expected and block_id not in seen:
                normalized.append(block_id)
                seen.add(block_id)
        for block_id in reader.required_ids:
            if block_id not in seen:
                normalized.append(block_id)
                seen.add(block_id)
        return normalized

    def _reduce(self, state: EvaluationState, notes: list[str], level: int) -> str:
        fn = getattr(self.judge, "reduce_notes", None)
        if callable(fn):
            summary = str(fn(state.question, state.answer, notes, level))
        else:
            clipped = [n[:240] for n in notes]
            summary = f"L{level} deterministic reduction ({len(notes)} findings): " + " | ".join(clipped)
        node_id = hashlib.sha256((str(level) + "\x1f" + "\x1e".join(notes)).encode()).hexdigest()[:20]
        state.reduction_nodes.append(ReductionNode(id=node_id, level=level, input_count=len(notes), summary=summary))
        return summary

    def _flush_working_notes(self, state: EvaluationState) -> None:
        if not state.working_notes:
            return
        state.reduced_notes.append(self._reduce(state, state.working_notes, level=1))
        state.working_notes = []

    def _compact_reduced_notes(self, state: EvaluationState) -> None:
        level = 2
        notes = list(state.reduced_notes)
        while len(notes) > self.reduction_batch_size:
            next_level: list[str] = []
            for i in range(0, len(notes), self.reduction_batch_size):
                batch = notes[i : i + self.reduction_batch_size]
                next_level.append(self._reduce(state, batch, level=level))
            notes = next_level
            level += 1
        state.reduced_notes = notes

    def _checkpoint(
        self, job_id: str, corpus_id: str, ordered: list[str], cursor: int, state: EvaluationState, complete: bool,
        *, final_score: float | None = None, final_rationale: str | None = None, status: str | None = None,
    ) -> None:
        self.store.put_checkpoint(
            EvaluationCheckpoint(
                job_id=job_id,
                corpus_id=corpus_id,
                ordered_block_ids=ordered,
                cursor=cursor,
                state=state,
                complete=complete,
                final_score=final_score,
                final_rationale=final_rationale,
                status=status or ("complete" if complete else "running"),
            )
        )

    def _sync_usage(self, state: EvaluationState) -> None:
        fn = getattr(self.judge, "usage_snapshot", None)
        if callable(fn):
            try:
                state.usage = fn()
            except Exception:
                pass

    def _emit_progress(self, job_id: str, corpus_id: str, coverage: "CoverageController", state: EvaluationState, status: str) -> None:
        if not self.progress_callback:
            return
        self._sync_usage(state)
        self.progress_callback({
            "job_id": job_id,
            "corpus_id": corpus_id,
            "coverage": coverage.coverage,
            "visited": len(coverage.expected & state.visited),
            "total": len(coverage.expected),
            "failed_blocks": len(set(state.failures) & coverage.expected),
            "evidence": len(state.evidence),
            "status": status,
            "usage": state.usage.model_dump(),
        })

    @staticmethod
    def _next_cursor(ordered: list[str], visited: set[str]) -> int:
        for i, block_id in enumerate(ordered):
            if block_id not in visited:
                return i
        return len(ordered)

    def _inspect_one(self, question: str, answer: str, block, notes_snapshot: list[str]) -> _InspectionOutcome:
        can_inspect = getattr(self.judge, "can_inspect", None)
        if callable(can_inspect) and not bool(can_inspect(block)):
            caps = ",".join(getattr(block, "required_capabilities", []) or []) or block.modality.value
            return _InspectionOutcome(block.id, None, False, 1, f"judge route cannot inspect required capability/modality: {caps}")
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                note, relevant = self.judge.inspect(question, answer, block, notes_snapshot)
                return _InspectionOutcome(block.id, note, relevant, attempt)
            except Exception as exc:  # worker failures are data, not silent drops
                last_error = exc
                if attempt < self.retry_attempts and self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds * attempt)
        return _InspectionOutcome(
            block.id,
            None,
            False,
            self.retry_attempts,
            f"{type(last_error).__name__}: {last_error}" if last_error else "inspection failed",
        )

    def _contextual_block(self, reader: CorpusReader, block_id: str):
        block = reader.read(block_id)
        supports_context = getattr(self.judge, "supports_neighbor_context", False)
        related = reader.related(block_id) if supports_context else []
        referenced = reader.references(block_id) if supports_context else []
        related_by_id = {x.id: x for x in [*related, *referenced]}
        related = list(related_by_id.values())
        if not supports_context or self.neighbor_context_chars <= 0:
            return block
        window = reader.neighbors(block_id)
        prev = window.previous if window.previous and window.previous.source.asset_id == block.source.asset_id else None
        nxt = window.next if window.next and window.next.source.asset_id == block.source.asset_id else None
        parts: list[str] = []
        if prev and prev.text:
            parts.append("<PREVIOUS_CONTEXT>\n" + prev.text[-self.neighbor_context_chars:])
        parts.append("<CURRENT_BLOCK>\n" + block.text)
        if nxt and nxt.text:
            parts.append("<NEXT_CONTEXT>\n" + nxt.text[:self.neighbor_context_chars])

        # Co-located textual/table representations are context only; they never count
        # as additional coverage visits for this inspection. This is especially useful
        # for PDF/PPT page text + visual pairs.
        related_text: list[str] = []
        related_media_paths: list[str] = []
        for peer in related:
            if peer.text and peer.modality.value in {"text", "table"}:
                related_text.append(
                    f"<{peer.modality.value.upper()}_COLOCATED block_id={peer.id}>\n"
                    + peer.text[: self.neighbor_context_chars * 2]
                )
            media_path = peer.metadata.get("media_path")
            if media_path and peer.modality.value == "image":
                related_media_paths.append(str(media_path))
        if related_text:
            parts.append("<COLOCATED_CONTEXT>\n" + "\n\n".join(related_text))

        return block.model_copy(update={
            "text": "\n\n".join(parts),
            "metadata": {
                **block.metadata,
                "contextmesh_neighbor_context": True,
                "contextmesh_related_block_ids": [x.id for x in related],
                "contextmesh_reference_block_ids": [x.id for x in referenced],
                "contextmesh_related_media_paths": related_media_paths[:4],
            },
        })

    def _preflight_unsupported(self, reader: CorpusReader, question: str = "preflight", answer: str = "preflight") -> dict[str, str]:
        """Find blocks the selected judge cannot inspect before expensive execution starts."""
        can_inspect = getattr(self.judge, "can_inspect", None)
        preflight_block = getattr(self.judge, "preflight_block", None)
        if not callable(can_inspect) and not callable(preflight_block):
            return {}
        unsupported: dict[str, str] = {}
        for block_id in reader.required_ids:
            block = self._contextual_block(reader, block_id)
            if callable(can_inspect) and not bool(can_inspect(block)):
                caps = ",".join(getattr(block, "required_capabilities", []) or []) or block.modality.value
                unsupported[block_id] = f"judge route cannot inspect required capability/modality: {caps}"
                continue
            if callable(preflight_block):
                reason = preflight_block(question, answer, block)
                if reason:
                    unsupported[block_id] = str(reason)
        return unsupported

    def _inspect_batch(self, reader: CorpusReader, state: EvaluationState, block_ids: list[str]) -> list[_InspectionOutcome]:
        # Every worker sees the same pre-batch state. Results are merged in corpus order,
        # making reduction deterministic regardless of completion order.
        notes_snapshot = list(state.model_context_notes())
        blocks = [self._contextual_block(reader, x) for x in block_ids]
        if self.max_workers == 1 or len(blocks) <= 1:
            return [self._inspect_one(state.question, state.answer, b, notes_snapshot) for b in blocks]

        by_id: dict[str, _InspectionOutcome] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="contextmesh") as pool:
            future_map = {
                pool.submit(self._inspect_one, state.question, state.answer, block, notes_snapshot): block.id
                for block in blocks
            }
            for fut in as_completed(future_map):
                out = fut.result()
                by_id[out.block_id] = out
        return [by_id[x] for x in block_ids]

    @staticmethod
    def _transition_ledger(state: EvaluationState) -> TransitionLedger:
        receipts = [TransitionReceipt.model_validate(x) for x in state.transition_receipts]
        return TransitionLedger(receipts=receipts)

    def _append_transition(
        self,
        state: EvaluationState,
        *,
        subject_id: str,
        action: TransitionAction,
        reason_codes: list[str],
        input_text: str = "",
        output_text: str = "",
        lossy: bool = False,
        metadata: dict | None = None,
    ) -> None:
        ledger = self._transition_ledger(state)
        receipt = ledger.append(
            subject_id=subject_id,
            from_stage=EvidenceStage.MODEL_VISIBLE,
            to_stage=EvidenceStage.INSPECTED,
            action=action,
            reason_codes=reason_codes,
            input_sha256=hashlib.sha256(input_text.encode("utf-8")).hexdigest() if input_text else None,
            output_sha256=hashlib.sha256(output_text.encode("utf-8")).hexdigest() if output_text else None,
            lossy=lossy,
            metadata=metadata or {},
        )
        state.transition_receipts.append(receipt.model_dump(mode="json"))

    @staticmethod
    def _semantic_coverage(
        expected: set[str],
        state: EvaluationState,
    ) -> CoverageSnapshot:
        snapshot = CoverageSnapshot()
        for block_id in expected:
            snapshot.mark(block_id, EvidenceStage.INGESTED)
            snapshot.mark(block_id, EvidenceStage.STORED)
            snapshot.mark(block_id, EvidenceStage.ELIGIBLE)
        for block_id in state.visited:
            if block_id in expected:
                snapshot.mark(block_id, EvidenceStage.MODEL_VISIBLE)
                snapshot.mark(block_id, EvidenceStage.INSPECTED)
        snapshot.failed_subjects = set(state.failures) & expected
        return snapshot

    def _merge_outcome(self, state: EvaluationState, reader: CorpusReader, outcome: _InspectionOutcome) -> None:
        state.inspection_attempts[outcome.block_id] = state.inspection_attempts.get(outcome.block_id, 0) + outcome.attempts
        block = reader.read(outcome.block_id)
        if outcome.error is not None:
            state.failures[outcome.block_id] = outcome.error
            self._append_transition(
                state,
                subject_id=outcome.block_id,
                action=TransitionAction.FAIL,
                reason_codes=["inspection_failed"],
                input_text=block.text or "",
                lossy=True,
                metadata={"error": outcome.error, "attempts": outcome.attempts},
            )
            return
        state.failures.pop(outcome.block_id, None)
        state.visited.add(outcome.block_id)
        self._append_transition(
            state,
            subject_id=outcome.block_id,
            action=TransitionAction.PRESERVE,
            reason_codes=["inspection_completed"],
            input_text=block.text or "",
            output_text=outcome.note or "",
            metadata={"relevant": outcome.relevant, "attempts": outcome.attempts},
        )
        if outcome.note:
            state.working_notes.append(outcome.note)
        if outcome.relevant:
            state.evidence.append(Evidence(block_id=block.id, note=outcome.note or "", source=block.source, modality=block.modality, atoms=extract_evidence_atoms(block, outcome.note or "")))

    def _result(
        self,
        corpus_id: str,
        job_id: str,
        state: EvaluationState,
        coverage: CoverageController,
        *,
        score,
        rationale,
        finalization_blockers: list[str] | None = None,
    ) -> EvaluationResult:
        expected = coverage.expected
        manifest = self.store.get_manifest(corpus_id)
        full_complete = coverage.complete and manifest.coverage_ready
        return EvaluationResult(
            corpus_id=corpus_id,
            score=score,
            coverage=coverage.coverage,
            complete=full_complete,
            visited_blocks=len(expected & state.visited),
            total_blocks=len(expected),
            evidence=state.evidence,
            rationale=rationale,
            job_id=job_id,
            reduction_nodes=len(state.reduction_nodes),
            reduced_context_items=len(state.model_context_notes()),
            failed_blocks=len(set(state.failures) & expected),
            inspection_attempts=sum(state.inspection_attempts.values()),
            execution_mode=self.execution_mode,
            usage=state.usage,
            ingest_coverage=manifest.ingest_coverage,
            semantic_coverage=manifest.semantic_coverage,
            ingest_ready=manifest.coverage_ready,
            evidence_atoms=sum(len(item.atoms) for item in state.evidence),
            evidence_kind_counts=evidence_kind_counts(state.evidence),
            execution_contract_mode=(state.execution_contract or {}).get("mode"),
            transition_receipts=len(state.transition_receipts),
            transition_chain_valid=self._transition_ledger(state).verify_chain(),
            finalization_blockers=finalization_blockers or [],
        )

    def preflight(self, corpus_id: str) -> dict:
        """Check ingest readiness and model-route capability before expensive execution."""
        reader = CorpusReader(self.store, corpus_id)
        manifest = reader.manifest
        unsupported = self._preflight_unsupported(reader)
        unsupported_caps = sorted({
            cap
            for block_id in unsupported
            for cap in (reader.read(block_id).required_capabilities or [reader.read(block_id).modality.value])
        })
        return {
            "corpus_id": corpus_id,
            "ready": manifest.coverage_ready and not unsupported,
            "ingest_ready": manifest.coverage_ready,
            "ingest_coverage": manifest.ingest_coverage,
            "semantic_coverage": manifest.semantic_coverage,
            "unresolved_units": manifest.unresolved_units,
            "required_capabilities": manifest.required_capabilities,
            "unsupported_capabilities": unsupported_caps,
            "unsupported_blocks": len(unsupported),
            "unsupported_block_ids": list(unsupported)[:200],
        }

    def evaluate(
        self,
        corpus_id: str,
        question: str,
        answer: str,
        order: list[str] | None = None,
        *,
        job_id: str | None = None,
        resume: bool = False,
        max_blocks: int | None = None,
        contract: ExecutionContract | None = None,
    ) -> EvaluationResult:
        reader = CorpusReader(self.store, corpus_id)
        ordered = self._ordered_ids(reader, question, order)
        expected = set(reader.required_ids)
        job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"

        if resume:
            checkpoint = self.store.get_checkpoint(corpus_id, job_id)
            if checkpoint.state.question != question or checkpoint.state.answer != answer:
                raise ValueError("resume request does not match checkpoint question/answer")
            state = checkpoint.state
            ordered = checkpoint.ordered_block_ids
            if contract is not None:
                current = state.execution_contract
                requested = contract.model_dump(mode="json")
                if current is not None and current != requested:
                    raise ValueError("resume request does not match checkpoint execution contract")
                state.execution_contract = requested
        else:
            state = EvaluationState(
                corpus_id=corpus_id,
                question=question,
                answer=answer,
                execution_contract=contract.model_dump(mode="json") if contract else None,
            )
            self._checkpoint(job_id, corpus_id, ordered, 0, state, False, status="queued")

        coverage = CoverageController(expected=expected, visited=state.visited)

        # Fail fast when the chosen route cannot consume one or more required source
        # channels. This prevents thousands of wasted calls before discovering that a
        # text-only model was selected for a visual/audio corpus.
        unsupported = self._preflight_unsupported(reader, question, answer)
        if unsupported:
            state.failures.update(unsupported)
            self._sync_usage(state)
            self._checkpoint(job_id, corpus_id, ordered, self._next_cursor(ordered, state.visited), state, False, status="capability_blocked")
            self._emit_progress(job_id, corpus_id, coverage, state, "capability_blocked")
            missing_caps = sorted({
                cap
                for block_id in unsupported
                for cap in (reader.read(block_id).required_capabilities or [reader.read(block_id).modality.value])
            })
            return self._result(
                corpus_id, job_id, state, coverage, score=None,
                rationale=(
                    "Evaluation blocked before execution: selected model route cannot inspect "
                    f"{len(unsupported)} required block(s). Missing/unsupported capabilities: {', '.join(missing_caps)}."
                ),
            )

        self._emit_progress(job_id, corpus_id, coverage, state, "running")
        remaining = [x for x in ordered if x in expected and x not in state.visited]
        if max_blocks is not None:
            remaining = remaining[: max(0, max_blocks)]

        for start in range(0, len(remaining), self.execution_batch_size):
            if self.cancellation_check and self.cancellation_check(corpus_id, job_id):
                cursor = self._next_cursor(ordered, state.visited)
                self._sync_usage(state)
                self._checkpoint(job_id, corpus_id, ordered, cursor, state, False, status="cancelled")
                self._emit_progress(job_id, corpus_id, coverage, state, "cancelled")
                return self._result(
                    corpus_id, job_id, state, coverage, score=None,
                    rationale="Evaluation cancelled by user. Progress is checkpointed and can be resumed later.",
                )
            batch_ids = remaining[start : start + self.execution_batch_size]
            for outcome in self._inspect_batch(reader, state, batch_ids):
                self._merge_outcome(state, reader, outcome)

            if len(state.working_notes) >= self.reduction_batch_size:
                self._flush_working_notes(state)
                if len(state.reduced_notes) >= self.reduction_batch_size * 2:
                    self._compact_reduced_notes(state)

            cursor = self._next_cursor(ordered, state.visited)
            self._sync_usage(state)
            self._checkpoint(job_id, corpus_id, ordered, cursor, state, False, status="running")
            self._emit_progress(job_id, corpus_id, coverage, state, "running")

        # A failed block is intentionally still missing from coverage and can be retried
        # by resuming the same job, including failures that lie before the old cursor.
        if not coverage.complete:
            cursor = self._next_cursor(ordered, state.visited)
            self._sync_usage(state)
            self._checkpoint(job_id, corpus_id, ordered, cursor, state, False, status="blocked" if state.failures else "paused")
            self._emit_progress(job_id, corpus_id, coverage, state, "blocked" if state.failures else "paused")
            reason = "Evaluation paused before full coverage; no final score is valid yet."
            if state.failures:
                reason += f" {len(set(state.failures) & expected)} block(s) failed after retries and remain pending."
            return self._result(corpus_id, job_id, state, coverage, score=None, rationale=reason)

        coverage.assert_complete()

        active_contract = (
            ExecutionContract.model_validate(state.execution_contract)
            if state.execution_contract is not None
            else None
        )
        if active_contract is not None:
            semantic_coverage = self._semantic_coverage(expected, state)
            blockers = semantic_coverage.finalization_blockers(active_contract)
            if blockers:
                self._sync_usage(state)
                rationale = (
                    "Execution contract blocked finalization: "
                    + "; ".join(blockers)
                    + ". No final score is valid until the required semantic stages are complete."
                )
                self._checkpoint(
                    job_id,
                    corpus_id,
                    ordered,
                    len(ordered),
                    state,
                    False,
                    status="contract_blocked",
                )
                self._emit_progress(job_id, corpus_id, coverage, state, "contract_blocked")
                return self._result(
                    corpus_id,
                    job_id,
                    state,
                    coverage,
                    score=None,
                    rationale=rationale,
                    finalization_blockers=blockers,
                )

        manifest = self.store.get_manifest(corpus_id)
        if not manifest.coverage_ready:
            self._sync_usage(state)
            rationale = (
                "Execution visited every currently addressable block, but ingest/semantic coverage is incomplete; "
                f"ingest={manifest.ingest_coverage:.3f}, semantic={manifest.semantic_coverage:.3f}, "
                f"unresolved_units={manifest.unresolved_units}. Final score is locked until unresolved source channels are repaired."
            )
            self._checkpoint(job_id, corpus_id, ordered, len(ordered), state, False, status="ingest_blocked")
            self._emit_progress(job_id, corpus_id, coverage, state, "ingest_blocked")
            return self._result(corpus_id, job_id, state, coverage, score=None, rationale=rationale)
        self._flush_working_notes(state)
        self._compact_reduced_notes(state)
        score, rationale = self.judge.finalize(state)
        self._sync_usage(state)
        self._checkpoint(job_id, corpus_id, ordered, len(ordered), state, True, final_score=score, final_rationale=rationale, status="complete")
        self._emit_progress(job_id, corpus_id, coverage, state, "complete")
        return self._result(corpus_id, job_id, state, coverage, score=score, rationale=rationale)
