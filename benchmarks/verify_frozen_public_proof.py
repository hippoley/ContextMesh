from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from contextmesh.frozen_proof import (
    FrozenProofMismatch,
    verify_frozen_public_proof,
)


def _load(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise FrozenProofMismatch(f"{path} must contain a JSON object")
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify a rebuilt public corpus/scale plan against committed frozen proof."
    )
    ap.add_argument("--download-manifest", type=Path, required=True)
    ap.add_argument("--gate4-plan", type=Path, required=True)
    ap.add_argument("--gate1-2-proof", type=Path, required=True)
    ap.add_argument("--gate4-preflight", type=Path, required=True)
    ap.add_argument("--corpus-manifest", type=Path)
    ap.add_argument("--needle-matrix", type=Path)
    ap.add_argument("--task-cases", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    try:
        report = verify_frozen_public_proof(
            download_manifest=_load(args.download_manifest),
            gate4_plan=_load(args.gate4_plan),
            gate12_proof=_load(args.gate1_2_proof),
            gate4_preflight=_load(args.gate4_preflight),
            corpus_manifest=(
                _load(args.corpus_manifest)
                if args.corpus_manifest
                else None
            ),
            needle_matrix=(
                _load(args.needle_matrix)
                if args.needle_matrix
                else None
            ),
            task_cases=(
                _load(args.task_cases)
                if args.task_cases
                else None
            ),
        )
    except FrozenProofMismatch as exc:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "verified": False,
                    "error": str(exc),
                    "provider_calls_made": 0,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"FROZEN_PUBLIC_PROOF_MISMATCH {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print("FROZEN_PUBLIC_PROOF_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
