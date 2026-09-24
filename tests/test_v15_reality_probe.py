from contextmesh.reality_probe import (
    ContextMeshFullCoverageBackend,
    LexicalTopKBackend,
    ProbeSelection,
    ProbeVerdict,
    evaluate_selection,
    extract_document_markers,
    issue_derived_scenarios,
    run_reality_probe_suite,
)


def _by_id():
    return {x.id: x for x in issue_derived_scenarios(crowding=16)}


def test_issue_derived_scenarios_keep_public_reality_sources():
    scenarios = issue_derived_scenarios(crowding=16)
    assert {x.id for x in scenarios} == {
        "rare-exception",
        "later-contradiction",
        "near-duplicate-crowding",
        "unsupported-query",
    }
    assert all(x.reality_sources for x in scenarios)
    assert any("3706" in url for x in scenarios for url in x.reality_sources)
    assert any("4462" in url for x in scenarios for url in x.reality_sources)


def test_lexical_topk_can_lose_decisive_exception_under_crowding():
    scenario = _by_id()["rare-exception"]
    selection = LexicalTopKBackend(top_k=5).select(scenario)
    assert "transfer-legal-hold" not in selection.selected_ids


def test_contextmesh_uses_ranking_as_schedule_not_eligibility_gate():
    scenario = _by_id()["rare-exception"]
    selection = ContextMeshFullCoverageBackend(workers=2).select(scenario)
    assert set(selection.selected_ids) == {x.id for x in scenario.documents}
    assert selection.ranked_ids[0] in {x.id for x in scenario.documents}


def test_probe_report_exposes_verdict_change_when_decisive_evidence_is_missing():
    report = run_reality_probe_suite(
        top_k=5,
        scenarios=[_by_id()["near-duplicate-crowding"]],
        backends=[LexicalTopKBackend(5), ContextMeshFullCoverageBackend(workers=2)],
    )
    topk = next(x for x in report.outcomes if x.backend == "lexical-topk")
    full = next(x for x in report.outcomes if x.backend == "contextmesh-full-coverage")
    assert topk.decisive_recall == 0.0
    assert topk.evidence_available_verdict == ProbeVerdict.UNSUPPORTED
    assert topk.verdict_correct is False
    assert full.decisive_recall == 1.0
    assert full.evidence_available_verdict == ProbeVerdict.CONTRADICTS
    assert full.verdict_correct is True
    assert full.coverage == 1.0


def test_unsupported_query_stays_unsupported_in_ground_truth_evidence_contract():
    scenario = _by_id()["unsupported-query"]
    report = run_reality_probe_suite(
        top_k=3,
        scenarios=[scenario],
        backends=[LexicalTopKBackend(3), ContextMeshFullCoverageBackend(workers=2)],
    )
    assert all(x.evidence_available_verdict == ProbeVerdict.UNSUPPORTED for x in report.outcomes)
    topk = next(x for x in report.outcomes if x.backend == "lexical-topk")
    assert topk.forced_context_when_unsupported is True


def test_cognee_result_marker_parser_tolerates_nested_result_envelopes():
    payload = {
        "results": [
            {"text": "CM_DOC_ID::alpha\nhello"},
            {"raw": {"value": "other CM_DOC_ID::beta content"}},
            {"duplicate": "CM_DOC_ID::alpha"},
        ]
    }
    assert extract_document_markers(payload) == ["alpha", "beta"]


def test_markdown_report_contains_aggregate_and_backends():
    report = run_reality_probe_suite(
        top_k=4,
        scenarios=[_by_id()["rare-exception"]],
        backends=[LexicalTopKBackend(4), ContextMeshFullCoverageBackend(workers=2)],
    )
    md = report.to_markdown()
    assert "ContextMesh Reality Probe" in md
    assert "lexical-topk" in md
    assert "contextmesh-full-coverage" in md
    assert report.by_backend["contextmesh-full-coverage"]["mean_decisive_recall"] == 1.0


def test_first_decisive_rank_can_live_beyond_visible_top_k():
    scenario = _by_id()["rare-exception"]
    ranked = [x.id for x in scenario.documents if x.id != "transfer-legal-hold"]
    ranked.insert(16, "transfer-legal-hold")
    selection = ProbeSelection(
        backend="deep-rank-control",
        selected_ids=ranked[:5],
        ranked_ids=ranked,
    )
    outcome = evaluate_selection(scenario, selection)
    assert outcome.decisive_recall == 0.0
    assert outcome.first_decisive_rank == 17
    assert outcome.evidence_available_verdict == ProbeVerdict.UNSUPPORTED
