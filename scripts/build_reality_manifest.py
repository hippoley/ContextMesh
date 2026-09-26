from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks" / "results"


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def build_manifest() -> dict:
    cognee = load("cognee-mmr-rank17-2026-09-26.json")
    ragflow = load("ragflow-d24-before-after-2026-09-26.json")
    dify = load("dify-42889-2026-09-24.json")
    mem0 = load("mem0-2.2.0-temporal-authority-2026-09-24.json")

    cognee_ranks_before = {row["released_decisive_rank"] for row in cognee["comparisons"]}
    cognee_ranks_after = {row["mmr_decisive_rank"] for row in cognee["comparisons"]}
    if len(cognee_ranks_before) != 1 or len(cognee_ranks_after) != 1:
        raise RuntimeError("Cognee public card requires one shared before/after decisive rank")

    active = mem0["active_filter_search"]
    default = mem0["default_search"]
    if not active or not default:
        raise RuntimeError("Mem0 public card requires non-empty default and active-filter searches")

    return {
        "schema_version": 1,
        "generated_from": "benchmarks/results",
        "verified_through": max(
            cognee["date"],
            ragflow["date"],
            dify["date"],
            mem0["date"],
        ),
        "cases": {
            "cognee": {
                "label": "decisive rank",
                "before": str(next(iter(cognee_ranks_before))),
                "after": str(next(iter(cognee_ranks_after))),
                "source_run": cognee["source_run"],
                "scenario_count": len(cognee["comparisons"]),
                "before_top5_visible": all(
                    row["released_top5_contains_decisive"] for row in cognee["comparisons"]
                ),
                "after_top5_visible": all(
                    row["mmr_top5_contains_decisive"] for row in cognee["comparisons"]
                ),
                "copy": (
                    "Cognee PR #3707's exact MMR selector moved the decisive source "
                    "into top-5 in both controlled fixtures."
                ),
                "trace": [
                    ["retrieved #" + str(next(iter(cognee_ranks_before))), "hit"],
                    ["eligible", "loss"],
                    ["MMR #" + str(next(iter(cognee_ranks_after))), "hit"],
                    ["visible", "hit"],
                ],
            },
            "ragflow": {
                "label": "effective fit budget",
                "before": f'{ragflow["before"]["effective_fit_budget_before_95_percent"] // 1024}K',
                "after": f'{ragflow["after"]["effective_fit_budget_before_95_percent"] // 1000}K',
                "before_exact": ragflow["before"]["effective_fit_budget_before_95_percent"],
                "after_exact": ragflow["after"]["effective_fit_budget_before_95_percent"],
                "source_run": ragflow["source_run"],
                "go_test_result": ragflow["validation"]["go_test_result"],
                "copy": (
                    "The patch keeps context fitting on context_length while preserving "
                    "max_output as the generation ceiling."
                ),
                "trace": [
                    ["resolved", "hit"],
                    ["budget bound", "loss"],
                    ["split contract", "hit"],
                    ["Go tests", "hit"],
                ],
            },
            "dify": {
                "label": "decisive span",
                "before": "read",
                "after": "hidden",
                "source_run": dify["source_run"],
                "source_bytes": dify["scenario"]["source_bytes"],
                "source_selected": dify["observed"]["source_selected"],
                "source_read": dify["observed"]["source_read"],
                "decisive_visible": dify["observed"][
                    "decisive_middle_marker_visible_to_model_via_shell"
                ],
                "copy": (
                    "The instruction source loaded, but the middle span disappeared "
                    "at the rendering/model-visibility boundary."
                ),
                "trace": [
                    ["selected", "hit"],
                    ["read", "hit"],
                    ["rendered", "loss"],
                    ["model-visible", "loss"],
                ],
            },
            "mem0": {
                "label": "authority",
                "before": f"{len(default)} facts",
                "after": f"{len(active)} active",
                "source_run": mem0["source_run"],
                "default_count": len(default),
                "active_count": len(active),
                "active_score": default[0]["score"],
                "contested_score": default[1]["score"] if len(default) > 1 else None,
                "copy": (
                    "Semantic retrieval exposed both histories; lifecycle state, "
                    "not similarity alone, resolved which fact stayed authoritative."
                ),
                "trace": [
                    ["stored", "hit"],
                    ["retrieved", "hit"],
                    ["authority", "loss"],
                    ["filtered", "hit"],
                ],
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the public Reality Lab manifest from machine-readable probe results."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".pages" / "reality-data.json",
    )
    args = parser.parse_args()

    manifest = build_manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "REALITY_MANIFEST_OK "
        f"cases={len(manifest['cases'])} verified_through={manifest['verified_through']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
