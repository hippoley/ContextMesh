from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from contextmesh.big_context_proof import (
    BigContextProofReport,
    Gate1CorpusSpec,
    Gate2NeedleSpec,
    Gate3Spec,
    Gate4Spec,
    Gate5Spec,
    ProofRunSnapshot,
    assemble_big_context_proof,
    evaluate_gate1_corpus,
    evaluate_gate3,
    evaluate_gate5_drift,
    load_needle_matrix,
    load_task_cases,
    run_batched_full_coverage_needles,
    run_scale_curve,
    run_task_baselines,
    snapshot_from_gate3,
    validate_needle_matrix,
    write_proof_artifact,
)
from contextmesh.providers import build_judge_from_route
from contextmesh.store import FileContextStore


def _load_reference(path: Path) -> ProofRunSnapshot:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "snapshot" in raw:
        if raw["snapshot"] is None:
            raise ValueError("reference proof does not contain a snapshot")
        raw = raw["snapshot"]
    return ProofRunSnapshot.model_validate(raw)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run ContextMesh Big Context Proof gates against an ingested corpus."
    )
    ap.add_argument("corpus_id")
    ap.add_argument("--route-id", required=True)
    ap.add_argument("--needles", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--store", default=".contextmesh/store")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--snapshot-output", type=Path)
    ap.add_argument("--drift-reference", type=Path)
    ap.add_argument("--model-context-tokens", type=int)
    ap.add_argument("--ratios", default="1,2,5,10,20")
    ap.add_argument("--min-assets", type=int, default=10)
    ap.add_argument("--max-assets", type=int, default=30)
    ap.add_argument("--min-format-families", type=int, default=3)
    ap.add_argument("--min-corpus-ratio", type=float, default=5.0)
    ap.add_argument("--min-needles", type=int, default=100)
    ap.add_argument("--min-needle-kinds", type=int, default=8)
    ap.add_argument("--needle-sample-size", type=int, default=24)
    ap.add_argument("--task-sample-size", type=int, default=12)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--model-version")
    ap.add_argument("--prompt-version", default="big-context-proof-v1")
    ap.add_argument("--chunk-policy", default="corpus-manifest")
    ap.add_argument("--reducer-policy", default="typed-monotonic")
    ap.add_argument("--run-id")
    ap.add_argument("--skip-scale", action="store_true")
    ap.add_argument("--require-all-gates", action="store_true")
    args = ap.parse_args()

    store = FileContextStore(args.store)
    manifest = store.get_manifest(args.corpus_id)
    routes = {route.id: route for route in store.list_model_routes() if route.enabled}
    route = routes.get(args.route_id)
    if route is None:
        raise SystemExit(f"enabled route not found: {args.route_id}")

    context_tokens = args.model_context_tokens or route.max_context_tokens
    if not context_tokens:
        raise SystemExit(
            "model context tokens are required: configure route.max_context_tokens "
            "or pass --model-context-tokens"
        )

    needles = load_needle_matrix(args.needles)
    tasks = load_task_cases(args.tasks)
    run_id = args.run_id or f"{args.route_id}-{int(time.time())}"

    gate1 = evaluate_gate1_corpus(
        manifest,
        Gate1CorpusSpec(
            min_assets=args.min_assets,
            max_assets=args.max_assets,
            min_format_families=args.min_format_families,
            min_corpus_to_context_ratio=args.min_corpus_ratio,
            model_context_tokens=context_tokens,
        ),
    )
    gate2 = validate_needle_matrix(
        needles,
        Gate2NeedleSpec(
            min_cases=args.min_needles,
            min_kinds=args.min_needle_kinds,
        ),
        manifest=manifest,
    )

    gate3 = None
    gate4 = None
    gate5 = None
    snapshot = None

    if gate1.status == "pass" and gate2.status == "pass":
        def judge_factory():
            return build_judge_from_route(route)

        needle_report = run_batched_full_coverage_needles(
            store,
            args.corpus_id,
            judge_factory,
            needles,
            max_workers=args.workers,
        )
        baselines = run_task_baselines(
            store,
            args.corpus_id,
            judge_factory,
            tasks,
            lexical_top_ks=(5, 20),
            max_workers=args.workers,
        )
        gate3 = evaluate_gate3(needle_report, baselines, Gate3Spec())

        snapshot = snapshot_from_gate3(
            gate3,
            route,
            run_id=run_id,
            model_version=args.model_version,
            prompt_version=args.prompt_version,
            chunk_policy=args.chunk_policy,
            reducer_policy=args.reducer_policy,
            metadata={
                "corpus_id": args.corpus_id,
                "needle_matrix": str(args.needles),
                "task_set": str(args.tasks),
            },
        )

        if gate3.status == "pass" and not args.skip_scale:
            ratios = [
                float(value.strip())
                for value in args.ratios.split(",")
                if value.strip()
            ]
            gate4 = run_scale_curve(
                store,
                args.corpus_id,
                judge_factory,
                needles,
                tasks,
                Gate4Spec(
                    ratios=ratios,
                    model_context_tokens=context_tokens,
                    needle_sample_size=args.needle_sample_size,
                    task_sample_size=args.task_sample_size,
                    required_max_ratio=max(ratios) if ratios else 20.0,
                ),
            )

        if args.drift_reference and snapshot is not None:
            reference = _load_reference(args.drift_reference)
            gate5 = evaluate_gate5_drift(
                reference,
                [snapshot],
                Gate5Spec(),
            )

    proof = assemble_big_context_proof(
        corpus_id=args.corpus_id,
        route_id=args.route_id,
        run_id=run_id,
        gate1=gate1,
        gate2=gate2,
        gate3=gate3,
        gate4=gate4,
        gate5=gate5,
        snapshot=snapshot,
    )
    write_proof_artifact(args.output, proof)
    if args.snapshot_output and snapshot is not None:
        write_proof_artifact(args.snapshot_output, snapshot)

    print("BIG_CONTEXT_PROOF_PASS" if proof.claim_proven else "BIG_CONTEXT_PROOF_NOT_YET_PROVEN")
    print(proof.model_dump_json(indent=2))

    if args.require_all_gates and not proof.claim_proven:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
