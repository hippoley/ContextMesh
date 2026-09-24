from contextmesh.diagnostics import (
    EvidenceFailureClass,
    EvidenceStage,
    build_authority_lifecycle,
    build_probe_lifecycle,
)


def test_ranked_but_cut_off_is_eligibility_loss():
    trace = build_probe_lifecycle(
        source_id="critical",
        decisive=True,
        rank=17,
        selected=False,
        source_bytes=1000,
        visible_bytes=0,
        visible_ranges=[],
        semantic_visible=False,
    )
    assert trace.failure_class == EvidenceFailureClass.ELIGIBILITY_LOSS
    assert trace.first_non_present_stage == EvidenceStage.ELIGIBLE.value
    assert trace.stage(EvidenceStage.RETRIEVED).rank == 17


def test_selected_but_middle_hidden_is_transport_visibility_loss():
    trace = build_probe_lifecycle(
        source_id="skill",
        decisive=True,
        rank=1,
        selected=True,
        source_bytes=11343,
        visible_bytes=8192,
        visible_ranges=[[0, 4096], [7247, 11343]],
        semantic_visible=False,
    )
    assert trace.failure_class == EvidenceFailureClass.TRANSPORT_VISIBILITY_LOSS
    assert trace.first_non_present_stage == EvidenceStage.MODEL_VISIBLE.value
    assert trace.model_visible_ratio == 8192 / 11343


def test_fully_visible_source_has_no_failure():
    trace = build_probe_lifecycle(
        source_id="ok",
        decisive=True,
        rank=4,
        selected=True,
        source_bytes=200,
        visible_bytes=200,
        visible_ranges=[[0, 200]],
        semantic_visible=True,
    )
    assert trace.failure_class == EvidenceFailureClass.NONE
    assert trace.first_non_present_stage is None
    assert trace.model_visible_ratio == 1.0


def test_authority_stage_distinguishes_visible_from_authoritative():
    trace = build_authority_lifecycle(
        source_id="memory-transient",
        status="contested",
        verified=False,
        selected_as_authority=False,
        reason="newer observation is visible but unverified and contested",
    )
    assert trace.stage(EvidenceStage.RETRIEVED).present is True
    authority = trace.stage(EvidenceStage.AUTHORITY)
    assert authority is not None
    assert authority.disposition.value == "unknown"
    assert trace.failure_class == EvidenceFailureClass.AUTHORITY_UNRESOLVED


def test_closed_memory_can_be_non_authoritative_without_being_a_failure():
    trace = build_authority_lifecycle(
        source_id="memory-old",
        status="superseded",
        verified=True,
        selected_as_authority=False,
        reason="preserved for audit but superseded by a verified successor",
    )
    authority = trace.stage(EvidenceStage.AUTHORITY)
    assert authority is not None
    assert authority.disposition.value == "excluded"
    assert trace.failure_class == EvidenceFailureClass.NONE
