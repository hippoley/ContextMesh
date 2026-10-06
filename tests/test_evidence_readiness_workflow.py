from pathlib import Path


def test_live_workflow_observes_readiness_without_hard_failure() -> None:
    workflow = Path(".github/workflows/big-context-live-proof.yml").read_text(encoding="utf-8")
    assert "- name: Observe evidence readiness" in workflow
    assert "--output /tmp/contextmesh-nist-proof/results/evidence-check.json" in workflow
    block = workflow.split("- name: Observe evidence readiness", 1)[1].split("- name: Summarize live run artifact", 1)[0]
    assert "--fail-on-hold" not in block
    assert "Observation mode only" in block
    assert "GITHUB_STEP_SUMMARY" in block
