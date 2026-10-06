from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from contextmesh.big_context_proof import (
    Gate4ScalePlanReport,
    _lexical_evidence_recall,
    _materialize_projection,
    load_needle_matrix,
)
from contextmesh.store import FileContextStore


def _fingerprint(block_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(block_ids).encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run a no-provider lexical retrieval curve over an exact frozen "
            "Gate 4 projection plan. This is baseline evidence, not Gate 4 PASS."
        )
    )
    ap.add_argument("corpus_id")
    ap.add_argument("--store", required=True)
    ap.add_argument("--needles", type=Path, required=True)
    ap.add_argument("--scale-plan", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args = ap.parse_args()

    store = FileContextStore(args.store)
    all_needles = load_needle_matrix(args.needles)
    plan = Gate4ScalePlanReport.model_validate_json(
        args.scale_plan.read_text(encoding="utf-8")
    )

    if plan.corpus_id != args.corpus_id:
        raise SystemExit(
            f"frozen plan corpus mismatch: {plan.corpus_id} != {args.corpus_id}"
        )
    if not plan.ready_for_live_gate4:
        raise SystemExit("frozen Gate 4 plan is not ready")
    if plan.blockers:
        raise SystemExit("frozen Gate 4 plan contains blockers")

    by_id = {case.id: case for case in all_needles}
    missing = [case_id for case_id in plan.selected_case_ids if case_id not in by_id]
    if missing:
        raise SystemExit(f"frozen plan references missing needle cases: {missing}")
    needles = [by_id[case_id] for case_id in plan.selected_case_ids]

    previous: set[str] = set()
    rows: list[dict[str, object]] = []
    for point in plan.points:
        current = set(point.block_ids)
        fingerprint = _fingerprint(point.block_ids)
        if fingerprint != point.projection_fingerprint:
            raise SystemExit(
                f"{point.requested_ratio:g}x projection fingerprint mismatch"
            )
        if not set(plan.anchor_block_ids).issubset(current):
            raise SystemExit(
                f"{point.requested_ratio:g}x projection lost frozen anchor evidence"
            )
        if previous and not previous.issubset(current):
            raise SystemExit(
                f"{point.requested_ratio:g}x projection is not nested"
            )
        previous = current

        with tempfile.TemporaryDirectory(prefix="contextmesh-offline-gate4-") as tmp:
            projected_store = FileContextStore(Path(tmp) / "store")
            projected_id = (
                f"{args.corpus_id}__offline_scale_"
                f"{str(point.requested_ratio).replace('.', '_')}"
            )
            manifest = _materialize_projection(
                store,
                args.corpus_id,
                projected_store,
                projected_id,
                list(point.block_ids),
            )
            top5 = _lexical_evidence_recall(
                projected_store, projected_id, needles, 5
            )
            top20 = _lexical_evidence_recall(
                projected_store, projected_id, needles, 20
            )

        rows.append(
            {
                "requested_ratio": point.requested_ratio,
                "actual_ratio": point.actual_ratio,
                "estimated_tokens": point.estimated_tokens,
                "selected_blocks": manifest.required_blocks,
                "selected_assets": len(manifest.assets),
                "projection_fingerprint": point.projection_fingerprint,
                "anchor_preserved": True,
                "nested_with_previous": point.nested_with_previous,
                "lexical_top_5_evidence_recall": top5,
                "lexical_top_20_evidence_recall": top20,
            }
        )

    first5 = float(rows[0]["lexical_top_5_evidence_recall"]) if rows else 0.0
    first20 = float(rows[0]["lexical_top_20_evidence_recall"]) if rows else 0.0
    min5 = min(
        (float(row["lexical_top_5_evidence_recall"]) for row in rows),
        default=0.0,
    )
    min20 = min(
        (float(row["lexical_top_20_evidence_recall"]) for row in rows),
        default=0.0,
    )

    payload = {
        "schema_version": 1,
        "evidence_class": "contextmesh-gate4-offline-retrieval-baseline",
        "claim_scope": (
            "No-provider retrieval-only scale curve over the exact frozen Gate 4 "
            "projections. This does not execute the live model and cannot pass Gate 4."
        ),
        "corpus_id": args.corpus_id,
        "provider_calls_made": 0,
        "model_tokens_billed": 0,
        "live_gate4_status": "not-run",
        "selected_case_ids": plan.selected_case_ids,
        "anchor_fingerprint": plan.anchor_fingerprint,
        "points": rows,
        "lexical_top_5_max_drop": first5 - min5,
        "lexical_top_20_max_drop": first20 - min20,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Gate 4 Offline Retrieval Baseline",
        "",
        "> Retrieval-only evidence. No provider/model call was made. "
        "This artifact cannot mark Gate 4 PASS.",
        "",
        "| Requested | Actual | Blocks | Assets | lexical top-5 | lexical top-20 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {requested_ratio:g}x | {actual_ratio:.4f}x | "
            "{selected_blocks} | {selected_assets} | {lexical_top_5_evidence_recall:.3f} | "
            "{lexical_top_20_evidence_recall:.3f} |".format(**row)
        )
    lines.extend(
        [
            "",
            f"Top-5 maximum drop: **{payload['lexical_top_5_max_drop']:.3f}**",
            f"Top-20 maximum drop: **{payload['lexical_top_20_max_drop']:.3f}**",
            "",
            "Live Gate 4 remains **NOT RUN** until an authorized provider route executes "
            "the same frozen projections.",
        ]
    )
    args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
