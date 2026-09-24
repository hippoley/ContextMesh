from contextmesh.diagnostics import (
    EvidenceFailureClass,
    EvidenceStage,
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
