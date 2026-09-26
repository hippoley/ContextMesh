from __future__ import annotations

import argparse
import asyncio
import json
import math
import uuid
from importlib.metadata import version
from pathlib import Path
from typing import Any

from contextmesh.reality_probe import extract_document_markers, issue_derived_scenarios


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


async def embed_texts(texts: list[str]) -> list[list[float]]:
    from cognee.infrastructure.databases.unified import get_unified_engine

    unified = await get_unified_engine()
    raw = await unified.vector.embedding_engine.embed_text(texts)
    return [list(map(float, row)) for row in raw]


async def run_scenario(
    scenario: Any,
    *,
    mode: str,
    top_k: int,
    fetch_k: int,
    lambda_mult: float,
    extractor: str,
    source_label: str,
) -> dict[str, Any]:
    import cognee
    from cognee.modules.search.types import SearchType

    dataset = f"contextmesh_cognee_mmr_{mode}_{scenario.id}_{uuid.uuid4().hex[:8]}"
    payloads = [f"CM_DOC_ID::{doc.id}\n{doc.text}" for doc in scenario.documents]

    remember_compat = "extractor-argument"
    try:
        remembered = await cognee.remember(
            payloads,
            dataset_name=dataset,
            self_improvement=False,
            extractor=extractor,
        )
    except TypeError as exc:
        if "Unexpected keyword arguments: extractor" not in str(exc):
            raise
        remember_compat = "extractor-argument-unsupported-retried-with-default"
        remembered = await cognee.remember(
            payloads,
            dataset_name=dataset,
            self_improvement=False,
        )
    if getattr(remembered, "status", None) == "errored":
        raise RuntimeError(f"Cognee remember failed: {getattr(remembered, 'error', None)}")

    if mode == "chunks":
        query_type = SearchType.CHUNKS
        search_top_k = max(fetch_k, len(scenario.documents))
        kwargs: dict[str, Any] = {}
    elif mode == "chunks-mmr":
        query_type = getattr(SearchType, "CHUNKS_MMR", None)
        if query_type is None:
            raise RuntimeError(
                "This Cognee build does not expose SearchType.CHUNKS_MMR. "
                "Run the MMR arm against PR #3707 or a release containing it."
            )
        search_top_k = len(scenario.documents)
        kwargs = {
            "retriever_specific_config": {
                "fetch_k": max(fetch_k, len(scenario.documents)),
                "lambda_mult": lambda_mult,
            }
        }
    else:
        raise ValueError(f"unknown mode: {mode}")

    results = await cognee.search(
        scenario.question,
        query_type=query_type,
        datasets=[dataset],
        top_k=search_top_k,
        **kwargs,
    )
    ranked_ids = extract_document_markers(results)

    known_ids = {doc.id for doc in scenario.documents}
    ranked_ids = [doc_id for doc_id in ranked_ids if doc_id in known_ids]
    top_ids = ranked_ids[:top_k]
    decisive_ids = list(scenario.decisive_ids)
    decisive_ranks = [
        ranked_ids.index(doc_id) + 1 for doc_id in decisive_ids if doc_id in ranked_ids
    ]

    by_id = {doc.id: doc for doc in scenario.documents}
    top_vectors = await embed_texts([by_id[doc_id].text for doc_id in top_ids])
    redundancy = pairwise_stats(top_vectors)

    contradiction_ids = set(scenario.contradiction_ids)
    return {
        "scenario": scenario.id,
        "title": scenario.title,
        "source": source_label,
        "mode": mode,
        "question": scenario.question,
        "total_documents": len(scenario.documents),
        "top_k": top_k,
        "fetch_k": fetch_k,
        "lambda_mult": lambda_mult if mode == "chunks-mmr" else None,
        "remember_compat": remember_compat,
        "ranked_ids": ranked_ids,
        "top_ids": top_ids,
        "decisive_ids": decisive_ids,
        "decisive_rank": min(decisive_ranks) if decisive_ranks else None,
        "top_k_contains_decisive": bool(set(top_ids) & set(decisive_ids)),
        "contradiction_available_at_cutoff": bool(set(top_ids) & contradiction_ids)
        or bool(set(top_ids) & set(decisive_ids)),
        "top_k_redundancy": redundancy,
    }


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    wanted = {"rare-exception", "near-duplicate-crowding"}
    scenarios = [
        scenario
        for scenario in issue_derived_scenarios(crowding=args.crowding)
        if scenario.id in wanted
    ]

    rows = []
    for scenario in scenarios:
        rows.append(
            await run_scenario(
                scenario,
                mode=args.mode,
                top_k=args.top_k,
                fetch_k=args.fetch_k,
                lambda_mult=args.lambda_mult,
                extractor=args.extractor,
                source_label=args.source,
            )
        )

    return {
        "kind": "contextmesh-cognee-mmr-rank17-probe",
        "source": args.source,
        "mode": args.mode,
        "cognee_version": version("cognee"),
        "configuration": {
            "top_k": args.top_k,
            "fetch_k": args.fetch_k,
            "lambda_mult": args.lambda_mult if args.mode == "chunks-mmr" else None,
            "crowding": args.crowding,
            "extractor": args.extractor,
        },
        "results": rows,
        "limits": [
            "Controlled synthetic corpora; not a general Cognee benchmark.",
            "CHUNKS baseline is the released package arm; CHUNKS_MMR is the unmerged PR #3707 arm.",
            "Contradiction availability is measured from selected evidence; no live answer-generation judge is used.",
            "Pairwise redundancy uses the active Cognee embedding engine over the selected source texts.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["chunks", "chunks-mmr"], required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fetch-k", type=int, default=50)
    parser.add_argument("--crowding", type=int, default=16)
    parser.add_argument("--lambda-mult", type=float, default=0.5)
    parser.add_argument("--extractor", default="gliner")
    args = parser.parse_args()

    report = asyncio.run(main_async(args))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
