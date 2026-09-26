from __future__ import annotations

import argparse
import ast
import json
import math
from pathlib import Path
from typing import Any, Callable


def load_exact_pr_mmr(source: Path) -> tuple[Callable[..., list[int]], str]:
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source))
    wanted = {"_cosine_similarity", "mmr_select"}
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    found = {node.name for node in nodes}
    missing = wanted - found
    if missing:
        raise RuntimeError(f"missing expected PR functions: {sorted(missing)}")
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = {"List": list}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["mmr_select"], text


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def pairwise_stats(vectors: list[list[float]]) -> dict[str, float | int | None]:
    values: list[float] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            values.append(cosine(vectors[i], vectors[j]))
    if not values:
        return {"pairs": 0, "mean_cosine": None, "max_cosine": None}
    return {
        "pairs": len(values),
        "mean_cosine": sum(values) / len(values),
        "max_cosine": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--pr-source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--lambda-mult", type=float, default=0.5)
    parser.add_argument("--pr-url", default="https://github.com/topoteretes/cognee/pull/3707")
    parser.add_argument(
        "--pr-head-sha",
        default="d1625f2a87e562da2ae95242f00b0a1866c2209b",
    )
    args = parser.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    mmr_select, source_text = load_exact_pr_mmr(Path(args.pr_source))

    rows = []
    for base in baseline["results"]:
        fixture = base["embedding_fixture"]
        candidate_order = list(fixture["candidate_order"])
        query_embedding = list(map(float, fixture["query_embedding"]))
        vectors_by_id = {
            doc_id: list(map(float, vector))
            for doc_id, vector in fixture["candidate_embeddings"].items()
        }
        candidate_vectors = [vectors_by_id[doc_id] for doc_id in candidate_order]

        # Run the exact PR selector through the full candidate list. MMR is prefix-stable:
        # the first K selections are identical to a direct top_k=K run, so this exposes
        # both the real top-5 eligibility result and a diagnostic full MMR rank.
        selected_indices = mmr_select(
            query_embedding,
            candidate_vectors,
            len(candidate_order),
            args.lambda_mult,
        )
        mmr_order = [candidate_order[index] for index in selected_indices]
        top_ids = mmr_order[: args.top_k]
        decisive_ids = list(base["decisive_ids"])
        decisive_ranks = [
            mmr_order.index(doc_id) + 1 for doc_id in decisive_ids if doc_id in mmr_order
        ]
        contradiction_ids = set(decisive_ids)
        rows.append({
            "scenario": base["scenario"],
            "source": f"exact mmr_select() from PR #3707 @ {args.pr_head_sha[:9]}",
            "candidate_source": baseline["source"],
            "lambda_mult": args.lambda_mult,
            "top_k": args.top_k,
            "candidate_order": candidate_order,
            "mmr_order": mmr_order,
            "top_ids": top_ids,
            "decisive_ids": decisive_ids,
            "decisive_rank": min(decisive_ranks) if decisive_ranks else None,
            "top_k_contains_decisive": bool(set(top_ids) & set(decisive_ids)),
            "contradiction_available_at_cutoff": bool(set(top_ids) & contradiction_ids),
            "top_k_redundancy": pairwise_stats(
                [vectors_by_id[doc_id] for doc_id in top_ids]
            ),
        })

    result = {
        "kind": "contextmesh-cognee-pr3707-exact-mmr-select-replay",
        "baseline_source": baseline["source"],
        "baseline_cognee_version": baseline["cognee_version"],
        "upstream_pr": args.pr_url,
        "upstream_head_sha": args.pr_head_sha,
        "algorithm_source_file": str(args.pr_source),
        "algorithm_source_contains_search_type": "class MMRRetriever" in source_text,
        "configuration": {
            "top_k": args.top_k,
            "lambda_mult": args.lambda_mult,
        },
        "results": rows,
        "limits": [
            "This executes the exact pure mmr_select() function from PR #3707 over candidate embeddings produced by the released Cognee 1.6.0 environment.",
            "It does not claim the unmerged PR is end-to-end runnable against current Cognee; the PR head still predates current remember() API behavior and requires an LLM path.",
            "The candidate order comes from live Cognee 1.6.0 CHUNKS deep retrieval on the same controlled corpora.",
            "A full MMR order is computed only to expose diagnostic decisive rank; its first top_k entries equal the selector's direct top_k prefix.",
        ],
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
