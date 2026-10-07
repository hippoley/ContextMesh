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


def test_explicit_empty_scope_rejects_any_resolved_contributor():
    receipt = ContractResolutionReceipt(
        field_id="search-methods",
        declared_scope=[],
        resolved_scope=["bm25", "cosine"],
    )
    assert receipt.disposition == ContractResolutionDisposition.SCOPE_EXPANSION
    assert receipt.compliant is False


def test_unspecified_scope_does_not_invent_a_scope_contract():
    receipt = ContractResolutionReceipt(
        field_id="search-methods",
        declared_scope=None,
        resolved_scope=["bm25", "cosine"],
    )
    assert receipt.disposition == ContractResolutionDisposition.PRESERVED
    assert receipt.compliant is True


def test_declared_scope_without_resolution_fails_closed():
    receipt = ContractResolutionReceipt(
        field_id="search-methods",
        declared_scope=["bm25"],
        resolved_scope=None,
    )
    assert receipt.disposition == ContractResolutionDisposition.UNRESOLVED
    assert receipt.compliant is False


def test_explicit_empty_scope_can_resolve_to_empty():
    receipt = ContractResolutionReceipt(
        field_id="search-methods",
        declared_scope=[],
        resolved_scope=[],
    )
    assert receipt.disposition == ContractResolutionDisposition.PRESERVED
    assert receipt.compliant is True


def test_explicit_falsy_scalar_replaced_by_default_is_unexpected_fallback():
    """Reality regression: Graphiti #1951 resolves explicit overlap_tokens=0 to a default."""
    receipt = ContractResolutionReceipt(
        field_id="overlap-tokens",
        declared_fingerprint="sha256:int:0",
        resolved_fingerprint="sha256:int:default-overlap",
        metadata={
            "reality_source": "getzep/graphiti#1951",
            "failure_shape": "explicit-falsy-value-replaced-by-default",
        },
    )
    assert receipt.disposition == ContractResolutionDisposition.UNEXPECTED_FALLBACK
    assert receipt.compliant is False
