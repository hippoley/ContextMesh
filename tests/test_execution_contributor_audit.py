from contextmesh.diagnostics import (
    ExecutionContributorAudit,
    ExecutionContributorDisposition,
)


def test_configured_contributor_must_execute():
    audit = ExecutionContributorAudit(
        contributor_id="bm25",
        configured=True,
        executed=False,
        contributed=False,
    )
    assert audit.disposition == ExecutionContributorDisposition.MISSING_EXECUTION
    assert audit.compliant is False


def test_excluded_contributor_must_not_execute():
    audit = ExecutionContributorAudit(
        contributor_id="cosine",
        configured=False,
        executed=True,
        contributed=False,
    )
    assert audit.disposition == ExecutionContributorDisposition.UNAUTHORIZED_EXECUTION
    assert audit.compliant is False


def test_excluded_contributor_must_not_affect_result():
    audit = ExecutionContributorAudit(
        contributor_id="cosine",
        configured=False,
        executed=True,
        contributed=True,
        metadata={"effect": "rrf-score"},
    )
    assert audit.disposition == ExecutionContributorDisposition.UNAUTHORIZED_CONTRIBUTION
    assert audit.compliant is False


def test_configured_executed_contributor_is_compliant():
    audit = ExecutionContributorAudit(
        contributor_id="bm25",
        configured=True,
        executed=True,
        contributed=True,
    )
    assert audit.disposition == ExecutionContributorDisposition.COMPLIANT
    assert audit.compliant is True
