from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .models import Modality
from .store import FileContextStore


class AuditIssue(BaseModel):
    severity: str  # error | warning
    code: str
    message: str
    block_id: str | None = None
    asset_path: str | None = None


class CorpusAuditReport(BaseModel):
    corpus_id: str
    ok: bool
    required_blocks: int
    checked_blocks: int
    media_payloads: int = 0
    issues: list[AuditIssue] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


def audit_corpus(store: FileContextStore, corpus_id: str) -> CorpusAuditReport:
    manifest = store.get_manifest(corpus_id)
    issues: list[AuditIssue] = []
    checked = 0
    media_payloads = 0
    seen: set[str] = set()

    required = manifest.coverage_ids()
    for block_id in required:
        if block_id in seen:
            issues.append(AuditIssue(severity="error", code="duplicate_required_id", message=f"duplicate required block id: {block_id}", block_id=block_id))
            continue
        seen.add(block_id)
        try:
            block = store.get_block(corpus_id, block_id)
        except Exception as exc:
            issues.append(AuditIssue(severity="error", code="missing_block", message=f"required block cannot be loaded: {exc}", block_id=block_id))
            continue
        checked += 1

        if not block.processable:
            issues.append(AuditIssue(severity="error", code="required_not_processable", message="required block is marked non-processable", block_id=block.id, asset_path=block.source.path))

        if block.modality in {Modality.TEXT, Modality.TABLE} and not (block.text or "").strip():
            issues.append(AuditIssue(severity="error", code="empty_textual_block", message=f"{block.modality.value} coverage block has no text", block_id=block.id, asset_path=block.source.path))

        if block.modality in {Modality.IMAGE, Modality.AUDIO, Modality.VIDEO}:
            media = block.metadata.get("media_path") or block.source.path
            p = Path(str(media))
            media_payloads += 1
            if not p.is_file():
                issues.append(AuditIssue(severity="error", code="missing_media_payload", message=f"media payload is missing: {p}", block_id=block.id, asset_path=block.source.path))
            elif p.stat().st_size <= 0:
                issues.append(AuditIssue(severity="error", code="empty_media_payload", message=f"media payload is empty: {p}", block_id=block.id, asset_path=block.source.path))

        if block.parent_id:
            try:
                store.get_block(corpus_id, block.parent_id)
            except Exception:
                issues.append(AuditIssue(severity="warning", code="missing_parent", message=f"parent block is missing: {block.parent_id}", block_id=block.id, asset_path=block.source.path))

        for direction, peer_id in (("prev", block.prev_id), ("next", block.next_id)):
            if not peer_id:
                continue
            try:
                peer = store.get_block(corpus_id, peer_id)
            except Exception:
                issues.append(AuditIssue(severity="warning", code="missing_sibling", message=f"{direction} sibling missing: {peer_id}", block_id=block.id, asset_path=block.source.path))
                continue
            backlink = peer.next_id if direction == "prev" else peer.prev_id
            if backlink != block.id:
                issues.append(AuditIssue(severity="warning", code="broken_sibling_backlink", message=f"{direction} sibling backlink does not point back to block", block_id=block.id, asset_path=block.source.path))

    if manifest.required_blocks != len(required):
        issues.append(AuditIssue(severity="error", code="manifest_required_count_mismatch", message=f"manifest required_blocks={manifest.required_blocks}, actual={len(required)}"))
    if manifest.total_blocks != len(manifest.block_ids):
        issues.append(AuditIssue(severity="warning", code="manifest_total_count_mismatch", message=f"manifest total_blocks={manifest.total_blocks}, block_ids={len(manifest.block_ids)}"))

    report_paths = {r.path for r in manifest.asset_reports}
    asset_paths = set(manifest.assets)
    missing_reports = asset_paths - report_paths
    for path in sorted(missing_reports):
        issues.append(AuditIssue(severity="error", code="missing_asset_report", message="asset has no coverage report", asset_path=path))

    errors = [x for x in issues if x.severity == "error"]
    return CorpusAuditReport(
        corpus_id=corpus_id,
        ok=not errors,
        required_blocks=len(required),
        checked_blocks=checked,
        media_payloads=media_payloads,
        issues=issues,
        stats={
            "ingest_coverage": manifest.ingest_coverage,
            "semantic_coverage": manifest.semantic_coverage,
            "coverage_ready": manifest.coverage_ready,
            "unresolved_units": manifest.unresolved_units,
            "modalities": manifest.modality_counts,
            "required_capabilities": manifest.required_capabilities,
        },
    )
