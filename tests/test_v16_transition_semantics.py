from contextmesh.diagnostics import EvidenceStage
from contextmesh.models import EvidenceKind
from contextmesh.semantics import (
    AuthorityState,
    CoverageSnapshot,
    ExecutionContract,
    ReductionReceipt,
    SemanticEvidenceUnit,
    TransitionAction,
    TransitionLedger,
    validate_monotonic_reduction,
)


def test_full_coverage_contract_requires_inspection_not_just_visibility():
    contract = ExecutionContract.full_coverage(["a", "b"])
    coverage = CoverageSnapshot()

    for subject in ["a", "b"]:
        for stage in [
            EvidenceStage.INGESTED,
            EvidenceStage.STORED,
            EvidenceStage.ELIGIBLE,
            EvidenceStage.MODEL_VISIBLE,
        ]:
            coverage.mark(subject, stage)

    assert coverage.can_finalize(contract) is False
    assert coverage.finalization_blockers(contract) == ["inspected:missing=2"]

    coverage.mark("a", EvidenceStage.INSPECTED)
    coverage.mark("b", EvidenceStage.INSPECTED)
    assert coverage.can_finalize(contract) is True


def test_authority_contract_blocks_unresolved_fact():
    contract = ExecutionContract.authority_resolution(["fact-1"])
    coverage = CoverageSnapshot()

    for stage in [
        EvidenceStage.INGESTED,
        EvidenceStage.STORED,
        EvidenceStage.RETRIEVED,
        EvidenceStage.AUTHORITY,
    ]:
        coverage.mark("fact-1", stage)

    coverage.unresolved_authority_subjects.add("fact-1")
    assert coverage.can_finalize(contract) is False
    assert coverage.finalization_blockers(contract) == ["authority-unresolved=1"]

    coverage.unresolved_authority_subjects.clear()
    assert coverage.can_finalize(contract) is True


def test_transition_ledger_is_hash_chained_and_tamper_evident():
    ledger = TransitionLedger()
    first = ledger.append(
        subject_id="block-17",
        to_stage=EvidenceStage.RETRIEVED,
        action=TransitionAction.PRESERVE,
        reason_codes=["ranked"],
        metadata={"rank": 17},
    )
    second = ledger.append(
        subject_id="block-17",
        from_stage=EvidenceStage.RETRIEVED,
        to_stage=EvidenceStage.ELIGIBLE,
        action=TransitionAction.EXCLUDE,
        reason_codes=["top_k_cutoff"],
        policy_id="top-k",
        policy_version="5",
        lossy=True,
    )

    assert first.previous_hash is None
    assert second.previous_hash == first.receipt_hash
    assert ledger.verify_chain() is True

    ledger.receipts[0].metadata["rank"] = 1
    assert ledger.verify_chain() is False


def test_monotonic_reduction_rejects_dropped_exception():
    exception = SemanticEvidenceUnit(
        id="e-exception",
        kind=EvidenceKind.EXCEPTION,
        text="Except where section 17.4 applies.",
        source_ids={"contract-17"},
        decisive=True,
    )
    generic = SemanticEvidenceUnit(
        id="e-claim",
        kind=EvidenceKind.CLAIM,
        text="The agreement permits termination.",
        source_ids={"contract-01"},
    )

    result = validate_monotonic_reduction(
        [exception, generic],
        [generic],
        ReductionReceipt(
            input_ids=["e-exception", "e-claim"],
            output_ids=["e-claim"],
            dropped_ids=["e-exception"],
            reason_codes=["summary-compaction"],
        ),
    )

    assert result.ok is False
    assert "critical/decisive evidence dropped: e-exception" in result.errors


def test_monotonic_reduction_allows_redundancy_merge_with_provenance():
    a = SemanticEvidenceUnit(
        id="a",
        kind=EvidenceKind.CLAIM,
        text="Payment is due within 30 days.",
        source_ids={"invoice-policy-a"},
    )
    b = SemanticEvidenceUnit(
        id="b",
        kind=EvidenceKind.CLAIM,
        text="Invoices are payable in 30 days.",
        source_ids={"invoice-policy-b"},
    )
    merged = SemanticEvidenceUnit(
        id="m",
        kind=EvidenceKind.CLAIM,
        text="Payment is due within 30 days.",
        source_ids={"invoice-policy-a", "invoice-policy-b"},
    )

    result = validate_monotonic_reduction(
        [a, b],
        [merged],
        ReductionReceipt(
            input_ids=["a", "b"],
            output_ids=["m"],
            merged_from={"m": ["a", "b"]},
            reason_codes=["semantic-redundancy"],
        ),
    )

    assert result.ok is True
    assert result.errors == []


def test_monotonic_reduction_preserves_unresolved_authority():
    contested = SemanticEvidenceUnit(
        id="c",
        kind=EvidenceKind.CLAIM,
        text="Database port is 6543.",
        source_ids={"memory-new"},
        authority_state=AuthorityState.CONTESTED,
    )
    resolved = SemanticEvidenceUnit(
        id="m",
        kind=EvidenceKind.CLAIM,
        text="Database port is 6543.",
        source_ids={"memory-new"},
        authority_state=AuthorityState.ACTIVE,
    )

    result = validate_monotonic_reduction(
        [contested],
        [resolved],
        ReductionReceipt(
            input_ids=["c"],
            output_ids=["m"],
            merged_from={"m": ["c"]},
        ),
    )

    assert result.ok is False
    assert "unresolved authority merged into resolved output: c->m" in result.errors


def test_progressive_evaluator_persists_contract_and_transition_receipts(tmp_path):
    from contextmesh.ingest import ingest_paths
    from contextmesh.judges import HeuristicJudge
    from contextmesh.runtime import ProgressiveEvaluator
    from contextmesh.store import FileContextStore

    source = tmp_path / "contract.txt"
    source.write_text(
        ("ordinary clause. " * 800)
        + "Except where section 17.4 applies. "
        + ("ordinary clause. " * 800),
        encoding="utf-8",
    )
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(
        [source],
        store,
        "corp_v16_contract",
        window_chars=1200,
        overlap_chars=80,
    )
    contract = ExecutionContract.full_coverage(manifest.coverage_ids())

    result = ProgressiveEvaluator(store, HeuristicJudge()).evaluate(
        "corp_v16_contract",
        "Does any exception apply?",
        "No exception applies.",
        contract=contract,
    )

    assert result.complete is True
    assert result.execution_contract_mode == "full-coverage"
    assert result.finalization_blockers == []
    assert result.transition_receipts == manifest.required_blocks
    assert result.transition_chain_valid is True


def test_resume_continues_transition_hash_chain(tmp_path):
    from contextmesh.ingest import ingest_paths
    from contextmesh.judges import HeuristicJudge
    from contextmesh.runtime import ProgressiveEvaluator
    from contextmesh.store import FileContextStore

    source = tmp_path / "resume.txt"
    source.write_text("alpha beta gamma " * 1800, encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(
        [source],
        store,
        "corp_v16_resume",
        window_chars=1000,
        overlap_chars=50,
    )
    contract = ExecutionContract.full_coverage(manifest.coverage_ids())
    evaluator = ProgressiveEvaluator(store, HeuristicJudge())

    partial = evaluator.evaluate(
        "corp_v16_resume",
        "alpha?",
        "answer",
        job_id="job_v16_resume",
        max_blocks=1,
        contract=contract,
    )
    assert partial.complete is False
    assert partial.transition_receipts == 1
    assert partial.transition_chain_valid is True

    completed = evaluator.evaluate(
        "corp_v16_resume",
        "alpha?",
        "answer",
        job_id="job_v16_resume",
        resume=True,
        contract=contract,
    )
    assert completed.complete is True
    assert completed.transition_receipts == manifest.required_blocks
    assert completed.transition_chain_valid is True
