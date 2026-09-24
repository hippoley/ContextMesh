from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .benchmark import ScorePreservationBenchmark
from .audit import audit_corpus
from .fidelity import NeedleProbe, run_live_needles
from .ingest import ingest_paths
from .judges import HeuristicJudge, OpenAICompatibleJudge
from .reader import CorpusReader
from .reality_probe import (
    CogneeChunksBackend,
    ContextMeshFullCoverageBackend,
    LexicalTopKBackend,
    LiveProbeVerdictJudge,
    issue_derived_scenarios,
    run_reality_probe_suite,
)
from .runtime import ProgressiveEvaluator
from .store import FileContextStore


def _evaluator(store, args, judge=None):
    return ProgressiveEvaluator(
        store,
        judge or HeuristicJudge(),
        reduction_batch_size=getattr(args, "reduction_batch_size", 32),
        max_workers=getattr(args, "workers", 1),
        retry_attempts=getattr(args, "retries", 1),
    )


def main() -> None:
    p = argparse.ArgumentParser(prog="contextmesh")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("ingest")
    i.add_argument("corpus_id")
    i.add_argument("paths", nargs="+")
    i.add_argument("--store", default=".contextmesh/store")

    e = sub.add_parser("evaluate")
    e.add_argument("corpus_id")
    e.add_argument("question")
    e.add_argument("answer")
    e.add_argument("--store", default=".contextmesh/store")
    e.add_argument("--max-blocks", type=int)
    e.add_argument("--job-id")
    e.add_argument("--resume", action="store_true")
    e.add_argument("--workers", type=int, default=1)
    e.add_argument("--retries", type=int, default=1)
    e.add_argument("--reduction-batch-size", type=int, default=32)

    b = sub.add_parser("benchmark")
    b.add_argument("corpus_id")
    b.add_argument("question")
    b.add_argument("answer")
    b.add_argument("--store", default=".contextmesh/store")
    b.add_argument("--workers", type=int, default=1)
    b.add_argument("--retries", type=int, default=1)
    b.add_argument("--reduction-batch-size", type=int, default=32)
    b.add_argument("--tolerance", type=float, default=1.0)
    b.add_argument("--max-direct-chars", type=int, default=250000)

    r = sub.add_parser("read")
    r.add_argument("corpus_id")
    r.add_argument("block_id")
    r.add_argument("--store", default=".contextmesh/store")

    s = sub.add_parser("search")
    s.add_argument("corpus_id")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--store", default=".contextmesh/store")

    f = sub.add_parser("fidelity-live", help="run live model-level needle recovery over selected assets")
    f.add_argument("corpus_id")
    f.add_argument("--route-id", required=True)
    f.add_argument("--probe", action="append", default=[], help="asset=EXACT_NEEDLE; repeat for multiple assets")
    f.add_argument("--store", default=".contextmesh/store")

    a = sub.add_parser("audit", help="validate corpus addressability and payload integrity")
    a.add_argument("corpus_id")
    a.add_argument("--store", default=".contextmesh/store")

    serve = sub.add_parser("serve", help="start the ContextMesh workspace and admin console")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--reload", action="store_true")

    worker = sub.add_parser("worker", help="run a durable ContextMesh ingest/evaluation worker")
    worker.add_argument("--data", default=".contextmesh")
    worker.add_argument("--poll-seconds", type=float, default=0.5)
    worker.add_argument("--lease-seconds", type=float, default=180.0)
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--worker-id")

    rp = sub.add_parser("reality-probe", help="compare retrieval eligibility against full-coverage execution")
    rp.add_argument("--backend", action="append", choices=["lexical", "contextmesh", "cognee"], default=[])
    rp.add_argument("--top-k", type=int, default=5)
    rp.add_argument("--crowding", type=int, default=24)
    rp.add_argument("--scenario", action="append", default=[], help="run only named scenario(s)")
    rp.add_argument("--workers", type=int, default=4)
    rp.add_argument("--store", default=".contextmesh/store")
    rp.add_argument("--route-id", help="optional configured model route for a live verdict pass")
    rp.add_argument("--cognee-extractor", help="optional Cognee extractor override")
    rp.add_argument("--format", choices=["json", "markdown"], default="json")

    args = p.parse_args()
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("contextmesh.api:app", host=args.host, port=args.port, reload=args.reload)
        return
    if args.cmd == "worker":
        os.environ["CONTEXTMESH_DATA"] = args.data
        os.environ["CONTEXTMESH_EMBEDDED_WORKER"] = "0"
        from .api import run_worker_loop
        run_worker_loop(
            poll_seconds=args.poll_seconds,
            lease_seconds=args.lease_seconds,
            once=args.once,
            worker_id=args.worker_id,
        )
        return
    if args.cmd == "reality-probe":
        store = FileContextStore(args.store)
        requested = args.backend or ["lexical", "contextmesh"]
        backends = []
        if "lexical" in requested:
            backends.append(LexicalTopKBackend(args.top_k))
        if "contextmesh" in requested:
            backends.append(ContextMeshFullCoverageBackend(workers=args.workers))
        if "cognee" in requested:
            backends.append(CogneeChunksBackend(args.top_k, extractor=args.cognee_extractor))

        live_judge = None
        if args.route_id:
            routes = {route.id: route for route in store.list_model_routes() if route.enabled}
            route = routes.get(args.route_id)
            if route is None:
                raise SystemExit(f"enabled route not found: {args.route_id}")
            api_key = os.getenv(route.api_key_env, "EMPTY") if route.api_key_env else "EMPTY"
            judge = OpenAICompatibleJudge(
                route.model,
                route.base_url,
                api_key,
                route_id=route.id,
                input_cost_per_million=route.input_cost_per_million,
                output_cost_per_million=route.output_cost_per_million,
                capabilities=route.capabilities,
                max_context_tokens=route.max_context_tokens,
                request_timeout_seconds=route.request_timeout_seconds,
            )
            live_judge = LiveProbeVerdictJudge(judge)

        scenarios = issue_derived_scenarios(crowding=args.crowding)
        if args.scenario:
            wanted = set(args.scenario)
            known = {x.id for x in scenarios}
            unknown = sorted(wanted - known)
            if unknown:
                raise SystemExit(f"unknown reality-probe scenario(s): {', '.join(unknown)}")
            scenarios = [x for x in scenarios if x.id in wanted]
        report = run_reality_probe_suite(
            top_k=args.top_k,
            backends=backends,
            scenarios=scenarios,
            live_judge=live_judge,
        )
        print(report.to_markdown() if args.format == "markdown" else report.model_dump_json(indent=2))
        return

    store = FileContextStore(args.store)
    if args.cmd == "ingest":
        m = ingest_paths([Path(x) for x in args.paths], store, args.corpus_id)
        print(m.model_dump_json(indent=2))
    elif args.cmd == "evaluate":
        result = _evaluator(store, args).evaluate(
            args.corpus_id,
            args.question,
            args.answer,
            max_blocks=args.max_blocks,
            job_id=args.job_id,
            resume=args.resume,
        )
        print(result.model_dump_json(indent=2))
    elif args.cmd == "benchmark":
        judge = HeuristicJudge()
        report = ScorePreservationBenchmark(
            _evaluator(store, args, judge),
            judge,
            max_direct_chars=args.max_direct_chars,
            tolerance=args.tolerance,
        ).run(args.corpus_id, args.question, args.answer)
        print(report.model_dump_json(indent=2))
    elif args.cmd == "fidelity-live":
        routes = {r.id: r for r in store.list_model_routes() if r.enabled}
        route = routes.get(args.route_id)
        if route is None:
            raise SystemExit(f"enabled route not found: {args.route_id}")
        probes = []
        for raw in args.probe:
            if "=" not in raw:
                raise SystemExit("--probe must be asset=EXACT_NEEDLE")
            asset, needle = raw.split("=", 1)
            probes.append(NeedleProbe(asset=asset, needle=needle))
        if not probes:
            raise SystemExit("at least one --probe is required")
        api_key = os.getenv(route.api_key_env, "EMPTY") if route.api_key_env else "EMPTY"
        judge = OpenAICompatibleJudge(
            route.model, route.base_url, api_key, route_id=route.id,
            input_cost_per_million=route.input_cost_per_million,
            output_cost_per_million=route.output_cost_per_million,
            capabilities=route.capabilities,
        )
        print(run_live_needles(store, args.corpus_id, judge, probes).model_dump_json(indent=2))
    elif args.cmd == "audit":
        print(audit_corpus(store, args.corpus_id).model_dump_json(indent=2))
    elif args.cmd == "read":
        print(json.dumps(CorpusReader(store, args.corpus_id).read(args.block_id).model_dump(), indent=2, default=str))
    else:
        reader = CorpusReader(store, args.corpus_id)
        print(json.dumps(reader.lexical_order(args.query)[: args.limit], indent=2))

if __name__ == "__main__":
    main()
