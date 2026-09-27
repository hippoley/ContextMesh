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
    build_decision_bundle,
    reduce_semantic_units,
    render_decision_bundle_checked,
    shard_decision_bundle,
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


def test_canonical_reducer_merges_only_same_typed_fact():
    a = SemanticEvidenceUnit(
        id="a",
        kind=EvidenceKind.REQUIREMENT,
        text="Payment must be made within 30 days.",
        source_ids={"doc-a"},
    )
    b = SemanticEvidenceUnit(
        id="b",
        kind=EvidenceKind.REQUIREMENT,
        text="Payment must be made within 30 days.",
        source_ids={"doc-b"},
    )
    near_duplicate = SemanticEvidenceUnit(
        id="c",
        kind=EvidenceKind.REQUIREMENT,
        text="Payment should usually be made within 30 days.",
        source_ids={"doc-c"},
    )

    reduced, receipt, validation = reduce_semantic_units([a, b, near_duplicate])

    assert validation.ok is True
    assert len(reduced) == 2
    merged = next(unit for unit in reduced if unit.id.startswith("red_"))
    assert merged.source_ids == {"doc-a", "doc-b"}
    assert set(receipt.merged_from[merged.id]) == {"a", "b"}
    assert any(unit.id == "c" for unit in reduced)


def test_decision_bundle_keeps_epistemic_categories_separate():
    units = [
        SemanticEvidenceUnit(
            id="claim",
            kind=EvidenceKind.CLAIM,
            text="Termination is permitted.",
            source_ids={"master"},
        ),
        SemanticEvidenceUnit(
            id="exception",
            kind=EvidenceKind.EXCEPTION,
            text="Except where section 17.4 applies.",
            source_ids={"amendment"},
        ),
        SemanticEvidenceUnit(
            id="conflict",
            kind=EvidenceKind.CONTRADICTION,
            text="The schedule requires 60-day notice.",
            source_ids={"schedule"},
            authority_state=AuthorityState.CONTESTED,
        ),
    ]

    bundle = build_decision_bundle(units)

    assert [x.id for x in bundle.claims] == ["claim"]
    assert [x.id for x in bundle.exceptions] == ["exception"]
    assert [x.id for x in bundle.contradictions] == ["conflict"]
    assert [x.id for x in bundle.unresolved_authority] == ["conflict"]
    assert bundle.source_ids == {"master", "amendment", "schedule"}


def test_evidence_atom_identity_is_stable_for_same_block():
    from contextmesh.evidence import extract_evidence_atoms
    from contextmesh.models import ContextBlock, Modality, SourceRef

    block = ContextBlock(
        id="block-1",
        corpus_id="c",
        modality=Modality.TEXT,
        text="Unless emergency maintenance is declared, service must remain available.",
        source=SourceRef(asset_id="asset-1", path="policy.md"),
    )
    first = extract_evidence_atoms(block, "Policy materially changes the answer.")
    second = extract_evidence_atoms(block, "Policy materially changes the answer.")

    assert first
    assert [x.id for x in first] == [x.id for x in second]
    assert all(x.id and x.id.startswith("ev_") for x in first)


def test_runtime_builds_decision_bundle_and_reduction_receipt(tmp_path):
    from contextmesh.ingest import ingest_paths
    from contextmesh.runtime import ProgressiveEvaluator
    from contextmesh.store import FileContextStore

    class DuplicateEvidenceJudge:
        def inspect(self, question, answer, block, notes):
            return "Payment must be made within 30 days.", True

        def reduce_notes(self, question, answer, notes, level):
            return "legacy explanation only"

        def finalize(self, state):
            assert state.decision_bundle is not None
            bundle = state.decision_bundle
            assert bundle["requirements"]
            return 88.0, "decision bundle consumed"

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("Payment must be made within 30 days.", encoding="utf-8")
    b.write_text("Payment must be made within 30 days.", encoding="utf-8")

    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([a, b], store, "corp_v16_bundle", window_chars=200, overlap_chars=0)

    result = ProgressiveEvaluator(
        store,
        DuplicateEvidenceJudge(),
        reduction_batch_size=2,
    ).evaluate(
        manifest.corpus_id,
        "When is payment due?",
        "Payment is due within 30 days.",
        job_id="job_v16_bundle",
        contract=ExecutionContract.full_coverage(manifest.coverage_ids()),
    )

    assert result.complete is True
    assert result.score == 88.0
    assert result.decision_bundle is not None
    assert result.decision_bundle["requirements"]
    assert result.semantic_units < result.evidence_atoms
    assert result.reduction_receipts >= 1

    checkpoint = store.get_checkpoint(manifest.corpus_id, "job_v16_bundle")
    merge_receipts = [
        receipt
        for receipt in checkpoint.state.transition_receipts
        if receipt["action"] == "merge"
    ]
    assert merge_receipts
    assert all(receipt["from_stage"] == "inspected" for receipt in merge_receipts)
    assert all(receipt["to_stage"] == "reduced" for receipt in merge_receipts)
    assert all(receipt["policy_id"] == "typed-canonical-reducer" for receipt in merge_receipts)


def test_decision_bundle_renderer_reports_overflow_instead_of_silent_truncation():
    units = [
        SemanticEvidenceUnit(
            id=f"exception-{i}",
            kind=EvidenceKind.EXCEPTION,
            text=("decisive exception " + str(i) + " ") * 20,
            source_ids={f"doc-{i}"},
        )
        for i in range(20)
    ]
    bundle = build_decision_bundle(units)
    rendered = render_decision_bundle_checked(bundle, max_chars=1200)

    assert rendered.complete is False
    assert rendered.required_chars > rendered.max_chars
    assert rendered.omitted_ids
    assert any(x.startswith("exception-") for x in rendered.omitted_ids)


def test_runtime_blocks_final_score_when_decision_bundle_cannot_fit(tmp_path):
    from contextmesh.ingest import ingest_paths
    from contextmesh.judges import OpenAICompatibleJudge
    from contextmesh.runtime import ProgressiveEvaluator
    from contextmesh.store import FileContextStore

    class NoNetworkJudge(OpenAICompatibleJudge):
        def inspect(self, question, answer, block, notes):
            return block.text, True

        def reduce_notes(self, question, answer, notes, level):
            return f"L{level}: legacy explanation compressed deterministically"

    source = tmp_path / "many-exceptions.txt"
    source.write_text(
        "\n".join(
            (
                f"Clause {i}: Unless exception-{i} applies, "
                + ("this unique requirement remains controlling. " * 8)
            )
            for i in range(80)
        ),
        encoding="utf-8",
    )
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(
        [source],
        store,
        "corp_v16_overflow",
        window_chars=480,
        overlap_chars=0,
    )
    judge = NoNetworkJudge(
        model="never-called",
        base_url="http://127.0.0.1:9",
        max_context_tokens=4096,
        reserve_output_tokens=512,
        chars_per_token_estimate=3.0,
    )

    result = ProgressiveEvaluator(
        store,
        judge,
        reduction_batch_size=8,
    ).evaluate(
        manifest.corpus_id,
        "Do any exceptions change the answer?",
        "No exceptions apply.",
        contract=ExecutionContract.full_coverage(manifest.coverage_ids()),
    )

    assert result.complete is True
    assert result.score is None
    assert result.finalization_blockers == ["decision-bundle-overflow"]
    assert "refusing lossy finalization" in result.rationale.lower()
    assert result.decision_bundle is not None


def test_api_materializes_full_coverage_contract_and_exposes_semantic_state(tmp_path, monkeypatch):
    import contextmesh.api as api_module
    from contextmesh.ingest import ingest_paths
    from contextmesh.judges import HeuristicJudge
    from contextmesh.runtime import ProgressiveEvaluator
    from contextmesh.semantics import ExecutionMode
    from contextmesh.store import FileContextStore

    source = tmp_path / "api-contract.txt"
    source.write_text(
        "Unless emergency maintenance applies, availability must remain above 99.95%.",
        encoding="utf-8",
    )
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([source], store, "corp_v16_api", window_chars=200, overlap_chars=0)
    monkeypatch.setattr(api_module, "STORE", store)

    req = api_module.EvaluateRequest(
        corpus_id=manifest.corpus_id,
        question="Is downtime always allowed?",
        answer="Yes.",
        execution_mode=ExecutionMode.FULL_COVERAGE,
    )
    contract = api_module._contract_for_request(req)
    assert contract.mode == ExecutionMode.FULL_COVERAGE
    assert contract.required_source_ids == set(manifest.coverage_ids())

    result = ProgressiveEvaluator(store, HeuristicJudge()).evaluate(
        manifest.corpus_id,
        req.question,
        req.answer,
        job_id="job_v16_api",
        contract=contract,
    )
    assert result.complete is True

    detail = api_module.job_detail(manifest.corpus_id, "job_v16_api")
    assert detail["execution_contract"]["mode"] == "full-coverage"
    assert detail["transition_receipts"] == manifest.required_blocks
    assert detail["transition_chain_valid"] is True
    assert detail["semantic_units"] >= 0
    assert detail["decision_bundle"] is not None


def test_api_rejects_retrieval_mode_on_full_coverage_job_endpoint(tmp_path, monkeypatch):
    import pytest
    import contextmesh.api as api_module
    from contextmesh.ingest import ingest_paths
    from contextmesh.semantics import ExecutionMode
    from contextmesh.store import FileContextStore

    source = tmp_path / "retrieval.txt"
    source.write_text("retrieval source", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([source], store, "corp_v16_retrieval", window_chars=200, overlap_chars=0)
    monkeypatch.setattr(api_module, "STORE", store)

    req = api_module.EvaluateRequest(
        corpus_id=manifest.corpus_id,
        question="find retrieval source",
        answer="",
        execution_mode=ExecutionMode.RETRIEVAL,
    )
    with pytest.raises(ValueError, match="served by /api/corpora"):
        api_module._contract_for_request(req)


def test_job_detail_separates_coverage_from_judgment_validity(tmp_path, monkeypatch):
    import contextmesh.api as api_module
    from contextmesh.ingest import ingest_paths
    from contextmesh.judges import HeuristicJudge
    from contextmesh.runtime import ProgressiveEvaluator
    from contextmesh.store import FileContextStore

    source = tmp_path / "status.txt"
    source.write_text("Unless maintenance applies, service must remain available.", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([source], store, "corp_v16_status", window_chars=200, overlap_chars=0)
    monkeypatch.setattr(api_module, "STORE", store)

    ProgressiveEvaluator(store, HeuristicJudge()).evaluate(
        manifest.corpus_id,
        "Is downtime always allowed?",
        "Yes.",
        job_id="job_v16_status",
        contract=ExecutionContract.full_coverage(manifest.coverage_ids()),
    )

    detail = api_module.job_detail(manifest.corpus_id, "job_v16_status")
    assert detail["coverage_complete"] is True
    assert detail["finalized"] is True
    assert detail["judgment_valid"] is True
    assert detail["finalization_blockers"] == []
    assert detail["inspection_coverage"] == 1.0
    assert detail["transitions"]["by_stage"]["inspected"] == manifest.required_blocks


def test_job_detail_and_semantic_artifacts_are_bounded_and_paginated(tmp_path, monkeypatch):
    import contextmesh.api as api_module
    from contextmesh.ingest import ingest_paths
    from contextmesh.runtime import ProgressiveEvaluator
    from contextmesh.store import FileContextStore

    class AllRelevantJudge:
        def inspect(self, question, answer, block, notes):
            return f"Unless exception for {block.id} applies, service must remain available.", True

        def reduce_notes(self, question, answer, notes, level):
            return f"L{level}: {len(notes)} findings"

        def finalize(self, state):
            return 90.0, "ok"

    source = tmp_path / "large-job.txt"
    source.write_text(
        "\n".join(f"Clause {i}: service must remain available unless exception {i} applies." for i in range(90)),
        encoding="utf-8",
    )
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([source], store, "corp_v16_pages", window_chars=90, overlap_chars=0)
    monkeypatch.setattr(api_module, "STORE", store)

    ProgressiveEvaluator(
        store,
        AllRelevantJudge(),
        reduction_batch_size=8,
    ).evaluate(
        manifest.corpus_id,
        "Which exceptions exist?",
        "None.",
        job_id="job_v16_pages",
        contract=ExecutionContract.full_coverage(manifest.coverage_ids()),
    )

    detail = api_module.job_detail(manifest.corpus_id, "job_v16_pages")
    assert detail["evidence_total"] > detail["evidence_preview_limit"]
    assert detail["evidence_truncated"] is True
    assert len(detail["evidence"]) == detail["evidence_preview_limit"]
    assert "items" not in detail["decision_bundle"]
    assert detail["detail_endpoints"]["transitions"].endswith("/transitions")

    evidence_page = api_module.job_evidence(
        manifest.corpus_id, "job_v16_pages", offset=50, limit=20
    )
    assert evidence_page["total"] == detail["evidence_total"]
    assert len(evidence_page["items"]) <= 20

    transition_page = api_module.job_transitions(
        manifest.corpus_id, "job_v16_pages", offset=0, limit=10, to_stage="inspected"
    )
    assert transition_page["total"] >= manifest.required_blocks
    assert len(transition_page["items"]) == 10
    assert transition_page["chain_valid"] is True

    exception_page = api_module.job_decision_bundle(
        manifest.corpus_id,
        "job_v16_pages",
        category="exceptions",
        offset=0,
        limit=5,
    )
    assert exception_page["total"] >= 1
    assert len(exception_page["items"]) <= 5
    assert exception_page["summary"]["available"] is True


def test_sync_evaluate_endpoint_materializes_contract(tmp_path, monkeypatch):
    import contextmesh.api as api_module
    from contextmesh.ingest import ingest_paths
    from contextmesh.store import FileContextStore

    source = tmp_path / "sync.txt"
    source.write_text("A required clause exists.", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([source], store, "corp_v16_sync", window_chars=200, overlap_chars=0)
    monkeypatch.setattr(api_module, "STORE", store)

    result = api_module.evaluate(
        api_module.EvaluateRequest(
            corpus_id=manifest.corpus_id,
            question="Does the clause exist?",
            answer="Yes.",
        )
    )

    assert result.execution_contract_mode == "full-coverage"
    assert result.coverage_complete is True
    assert result.judgment_valid is True


def test_workspace_recognizes_semantic_blocked_terminal_states():
    from pathlib import Path
    import contextmesh.api as api_module

    js = (api_module.WEB_ROOT / "contextmesh.js").read_text(encoding="utf-8")
    assert "contract_blocked" in js
    assert "decision_bundle_blocked" in js
    assert "execution_mode:'full-coverage'" in js
    assert "evidence_total" in js


def test_lossless_decision_sharding_preserves_every_evidence_id_exactly_once():
    units = []
    for i in range(30):
        kind = [
            EvidenceKind.EXCEPTION,
            EvidenceKind.CONTRADICTION,
            EvidenceKind.REQUIREMENT,
            EvidenceKind.CLAIM,
        ][i % 4]
        units.append(
            SemanticEvidenceUnit(
                id=f"unit-{i}",
                kind=kind,
                text=(f"unique evidence {i} " + "material detail " * 10).strip(),
                source_ids={f"doc-{i}"},
                authority_state=(
                    AuthorityState.CONTESTED if i % 7 == 0 else AuthorityState.ACTIVE
                ),
            )
        )

    bundle = build_decision_bundle(units)
    shard_set = shard_decision_bundle(bundle, max_chars=1800)

    assert shard_set.complete is True
    assert shard_set.shard_count > 1
    assert all(shard.char_count <= 1800 for shard in shard_set.shards)

    ids = [unit_id for shard in shard_set.shards for unit_id in shard.unit_ids]
    assert len(ids) == len(set(ids)) == bundle.total_units
    assert set(ids) == bundle.evidence_ids

    # Contested evidence remains one evidence unit, not a duplicate copy caused by
    # the unresolved-authority view.
    assert sum(1 for unit_id in ids if unit_id == "unit-0") == 1


def test_decision_shard_api_exposes_manifest_and_bounded_shard(tmp_path, monkeypatch):
    import contextmesh.api as api_module
    from contextmesh.ingest import ingest_paths
    from contextmesh.runtime import ProgressiveEvaluator
    from contextmesh.store import FileContextStore

    class ManyEvidenceJudge:
        def inspect(self, question, answer, block, notes):
            return (
                f"Unless exception for {block.id} applies, "
                + ("the requirement remains uniquely controlling. " * 5),
                True,
            )

        def reduce_notes(self, question, answer, notes, level):
            return f"L{level}: {len(notes)} findings"

        def finalize(self, state):
            return 80.0, "ok"

    source = tmp_path / "shards.txt"
    source.write_text(
        "\n".join(
            f"Clause {i}: requirement {i} applies unless exception {i}."
            for i in range(70)
        ),
        encoding="utf-8",
    )
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(
        [source], store, "corp_v16_shards", window_chars=80, overlap_chars=0
    )
    monkeypatch.setattr(api_module, "STORE", store)

    ProgressiveEvaluator(
        store, ManyEvidenceJudge(), reduction_batch_size=8
    ).evaluate(
        manifest.corpus_id,
        "Which exceptions matter?",
        "None.",
        job_id="job_v16_shards",
        contract=ExecutionContract.full_coverage(manifest.coverage_ids()),
    )

    shard_manifest = api_module.job_decision_bundle_shards(
        manifest.corpus_id, "job_v16_shards", max_chars=1400
    )
    assert shard_manifest["complete"] is True
    assert shard_manifest["shard_count"] > 1
    assert sum(x["unit_count"] for x in shard_manifest["shards"]) == shard_manifest["total_units"]
    assert all(x["char_count"] <= 1400 for x in shard_manifest["shards"])

    first = api_module.job_decision_bundle_shard(
        manifest.corpus_id, "job_v16_shards", shard_index=1, max_chars=1400
    )
    assert first["index"] == 1
    assert first["char_count"] <= 1400
    assert first["unit_ids"]
    assert "DECISION_SHARD 1/" in first["text"]


def test_large_provenance_set_uses_stable_reference_inside_shard():
    unit = SemanticEvidenceUnit(
        id="many-sources",
        kind=EvidenceKind.REQUIREMENT,
        text="Payment must be made within 30 days.",
        source_ids={f"block-{i:04d}" for i in range(120)},
    )
    bundle = build_decision_bundle([unit])
    shard_set = shard_decision_bundle(bundle, max_chars=1400)

    assert shard_set.complete is True
    assert shard_set.shard_count == 1
    shard = shard_set.shards[0]
    assert shard.unit_ids == ["many-sources"]
    assert "source_count=120" in shard.text
    assert "provenance_sha256=" in shard.text
    assert "block-0119" not in shard.text
    assert bundle.requirements[0].source_ids == {f"block-{i:04d}" for i in range(120)}
