from contextmesh.diagnostics import (
    ContractResolutionDisposition,
    ContractResolutionReceipt,
)


def test_declared_field_dropped_by_adapter_fails_closed():
    receipt = ContractResolutionReceipt(
        field_id="api-key",
        declared_fingerprint="sha256:declared",
        resolved_fingerprint=None,
    )
    assert receipt.disposition == ContractResolutionDisposition.DROPPED
    assert receipt.compliant is False


def test_silent_fallback_is_not_treated_as_explicit_transform():
    receipt = ContractResolutionReceipt(
        field_id="tokenizer",
        declared_fingerprint="sha256:hf-tokenizer",
        resolved_fingerprint="sha256:tiktoken",
    )
    assert receipt.disposition == ContractResolutionDisposition.UNEXPECTED_FALLBACK
    assert receipt.compliant is False


def test_authorized_fallback_is_compliant():
    receipt = ContractResolutionReceipt(
        field_id="credential-source",
        declared_fingerprint="sha256:config",
        resolved_fingerprint="sha256:env",
        fallback_authorized=True,
    )
    assert receipt.disposition == ContractResolutionDisposition.AUTHORIZED_FALLBACK
    assert receipt.compliant is True


def test_resolved_scope_must_not_expand_declared_scope():
    receipt = ContractResolutionReceipt(
        field_id="folder-filter",
        declared_scope=["Sample1", "green", "Support", "Data"],
        resolved_scope=["Sample1", "green", "Support", "Data", "Base"],
    )
    assert receipt.disposition == ContractResolutionDisposition.SCOPE_EXPANSION
    assert receipt.compliant is False


def test_preserved_contract_is_compliant():
    receipt = ContractResolutionReceipt(
        field_id="search-methods",
        declared_fingerprint="sha256:bm25",
        resolved_fingerprint="sha256:bm25",
        declared_scope=["bm25"],
        resolved_scope=["bm25"],
    )
    assert receipt.disposition == ContractResolutionDisposition.PRESERVED
    assert receipt.compliant is True
