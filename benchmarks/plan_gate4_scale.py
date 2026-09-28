from __future__ import annotations

import argparse
import json
from pathlib import Path

from contextmesh.big_context_proof import (
    Gate4Spec,
    load_needle_matrix,
    plan_gate4_scale,
    write_proof_artifact,
)
from contextmesh.store import FileContextStore


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Freeze a no-model-call Gate 4 scale plan over an ingested corpus."
    )
    ap.add_argument("corpus_id")
    ap.add_argument("--store", default=".contextmesh/store")
    ap.add_argument("--needles", type=Path, required=True)
    ap.add_argument("--model-context-tokens", type=int, required=True)
    ap.add_argument("--ratios", default="1,2,5,10,20")
    ap.add_argument("--needle-sample-size", type=int, default=12)
    ap.add_argument("--required-max-ratio", type=float, default=20.0)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    ratios = [
        float(value.strip())
        for value in args.ratios.split(",")
        if value.strip()
    ]
    if not ratios:
        raise SystemExit("at least one scale ratio is required")

    store = FileContextStore(args.store)
    needles = load_needle_matrix(args.needles)
    report = plan_gate4_scale(
        store,
        args.corpus_id,
        needles,
        Gate4Spec(
            ratios=ratios,
            model_context_tokens=args.model_context_tokens,
            needle_sample_size=args.needle_sample_size,
            task_sample_size=0,
            required_max_ratio=args.required_max_ratio,
        ),
    )
    write_proof_artifact(args.output, report)

    print("GATE4_SCALE_PLAN_READY" if report.ready_for_live_gate4 else "GATE4_SCALE_PLAN_BLOCKED")
    print(report.model_dump_json(indent=2))
    return 0 if report.ready_for_live_gate4 else 2


if __name__ == "__main__":
    raise SystemExit(main())
