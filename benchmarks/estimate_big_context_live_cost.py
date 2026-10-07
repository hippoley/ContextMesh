from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _load_cases(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return list(raw.get("cases", raw if isinstance(raw, list) else []))


def _payload_chars(cases: list[dict], *, task: bool) -> int:
    total = 0
    for case in cases:
        total += len(str(case.get("id") or ""))
        total += len(str(case.get("question") or ""))
        if task:
            total += len(str(case.get("candidate_answer") or ""))
        total += 48 if task else 32  # conservative JSON/protocol structure allowance
    return total


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Conservative preflight cost estimate for ContextMesh live proof."
    )
    ap.add_argument("--corpus-manifest", type=Path, required=True)
    ap.add_argument("--needles", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--context-tokens", type=int, required=True)
    ap.add_argument("--input-cny-per-million", type=float, required=True)
    ap.add_argument("--output-cny-per-million", type=float, required=True)
    ap.add_argument("--max-estimated-cost-cny", type=float, required=True)
    ap.add_argument("--image-reserve-tokens", type=int, default=4096)
    ap.add_argument("--block-prompt-reserve-tokens", type=int, default=900)
    ap.add_argument("--output-tokens-per-block", type=int, default=256)
    ap.add_argument("--final-input-tokens-per-task", type=int, default=16000)
    ap.add_argument("--final-output-tokens-per-task", type=int, default=768)
    ap.add_argument("--safety-factor", type=float, default=1.35)
    ap.add_argument("--run-scale", action="store_true")
    ap.add_argument("--scale-plan", type=Path)
    ap.add_argument("--ratios", default="1,2,5,10,20")
    ap.add_argument("--scale-needle-sample-size", type=int, default=12)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    numeric_inputs = {
        "context_tokens": args.context_tokens,
        "input_cny_per_million": args.input_cny_per_million,
        "output_cny_per_million": args.output_cny_per_million,
        "max_estimated_cost_cny": args.max_estimated_cost_cny,
        "image_reserve_tokens": args.image_reserve_tokens,
        "block_prompt_reserve_tokens": args.block_prompt_reserve_tokens,
        "output_tokens_per_block": args.output_tokens_per_block,
        "final_input_tokens_per_task": args.final_input_tokens_per_task,
        "final_output_tokens_per_task": args.final_output_tokens_per_task,
        "safety_factor": args.safety_factor,
    }
    for name, value in numeric_inputs.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise SystemExit(f"{name} must be finite")
        if value < 0:
            raise SystemExit(f"{name} must be non-negative")
    if args.context_tokens == 0:
        raise SystemExit("context_tokens must be greater than zero")
    if args.safety_factor == 0:
        raise SystemExit("safety_factor must be greater than zero")

    manifest = json.loads(args.corpus_manifest.read_text(encoding="utf-8"))
    needles = _load_cases(args.needles)
    tasks = _load_cases(args.tasks)

    blocks = int(manifest.get("required_blocks") or len(manifest.get("required_block_ids") or []))
    total_chars = int(manifest.get("total_chars") or 0)
    modalities = manifest.get("modality_counts") or {}
    image_blocks = int(modalities.get("image") or 0)
    avg_block_chars = total_chars / max(1, blocks)

    needle_payload = _payload_chars(needles, task=False)
    task_payload = _payload_chars(tasks, task=True)
    per_block_fixed = args.block_prompt_reserve_tokens

    # Gate 3 has two batched full-corpus traversals: needles and task evidence.
    needle_input = (
        blocks * (needle_payload + per_block_fixed)
        + total_chars
        + image_blocks * args.image_reserve_tokens
    )
    task_input = (
        blocks * (task_payload + per_block_fixed)
        + total_chars
        + image_blocks * args.image_reserve_tokens
    )
    traversal_output = (
        blocks * 2 * args.output_tokens_per_block
    )

    # Each task gets one separate final judgment after shared full-corpus evidence.
    final_input = len(tasks) * args.final_input_tokens_per_task
    final_output = len(tasks) * args.final_output_tokens_per_task

    # Same-model lexical top-5 and top-20 baselines. Direct-full-context is expected
    # to be blocked locally when the corpus exceeds the route budget, so it is not
    # charged as a network request here.
    lexical_input = int(
        len(tasks)
        * (
            (5 + 20) * avg_block_chars
            + 2 * args.block_prompt_reserve_tokens
        )
    )
    lexical_output = len(tasks) * 2 * args.final_output_tokens_per_task

    scale_input = 0
    scale_output = 0
    scale_plan_fingerprint = None
    scale_panel_case_ids: list[str] = []
    if args.run_scale:
        if args.scale_plan:
            scale_plan = json.loads(args.scale_plan.read_text(encoding="utf-8"))
            scale_panel_case_ids = list(scale_plan.get("selected_case_ids") or [])
            selected_case_set = set(scale_panel_case_ids)
            sampled = [
                case for case in needles
                if str(case.get("id") or "") in selected_case_set
            ]
            if len(sampled) != len(scale_panel_case_ids):
                raise SystemExit(
                    "scale plan references cases that are missing from the needle matrix"
                )
            scale_payload = _payload_chars(sampled, task=False)
            scale_plan_fingerprint = scale_plan.get("anchor_fingerprint")
            for point in scale_plan.get("points") or []:
                selected_blocks = int(point.get("selected_blocks") or 0)
                target = int(point.get("estimated_tokens") or 0)
                point_modalities = point.get("modality_counts") or {}
                selected_images = int(point_modalities.get("image") or 0)
                scale_input += (
                    selected_blocks * (scale_payload + per_block_fixed)
                    + target
                    + selected_images * args.image_reserve_tokens
                )
                scale_output += selected_blocks * args.output_tokens_per_block
        else:
            ratios = [float(x.strip()) for x in args.ratios.split(",") if x.strip()]
            sampled = needles[: max(1, args.scale_needle_sample_size)]
            scale_panel_case_ids = [
                str(case.get("id") or "") for case in sampled
            ]
            scale_payload = _payload_chars(sampled, task=False)
            image_fraction = image_blocks / max(1, blocks)
            for ratio in ratios:
                target = min(total_chars, int(args.context_tokens * ratio))
                selected_blocks = min(
                    blocks,
                    max(1, int(math.ceil(target / max(1.0, avg_block_chars)))),
                )
                selected_images = int(math.ceil(selected_blocks * image_fraction))
                scale_input += (
                    selected_blocks * (scale_payload + per_block_fixed)
                    + target
                    + selected_images * args.image_reserve_tokens
                )
                scale_output += selected_blocks * args.output_tokens_per_block

    raw_input = needle_input + task_input + final_input + lexical_input + scale_input
    raw_output = traversal_output + final_output + lexical_output + scale_output
    estimated_input = int(math.ceil(raw_input * args.safety_factor))
    estimated_output = int(math.ceil(raw_output * args.safety_factor))
    estimated_cost = (
        estimated_input / 1_000_000 * args.input_cny_per_million
        + estimated_output / 1_000_000 * args.output_cny_per_million
    )

    report = {
        "blocks": blocks,
        "image_blocks": image_blocks,
        "needle_cases": len(needles),
        "task_cases": len(tasks),
        "context_tokens": args.context_tokens,
        "safety_factor": args.safety_factor,
        "estimated_input_tokens": estimated_input,
        "estimated_output_tokens": estimated_output,
        "input_cny_per_million": args.input_cny_per_million,
        "output_cny_per_million": args.output_cny_per_million,
        "estimated_cost_cny": round(estimated_cost, 2),
        "max_estimated_cost_cny": args.max_estimated_cost_cny,
        "run_scale": args.run_scale,
        "scale_plan_fingerprint": scale_plan_fingerprint,
        "scale_panel_case_ids": scale_panel_case_ids,
        "components": {
            "gate3_needle_input": needle_input,
            "gate3_task_input": task_input,
            "gate3_final_input": final_input,
            "gate3_lexical_input": lexical_input,
            "gate4_scale_input": scale_input,
            "gate3_traversal_output": traversal_output,
            "gate3_final_output": final_output,
            "gate3_lexical_output": lexical_output,
            "gate4_scale_output": scale_output,
        },
        "within_budget": estimated_cost <= args.max_estimated_cost_cny,
        "note": (
            "Conservative architecture-level estimate, not a provider invoice. "
            "Image tokenization and model output lengths can vary; safety_factor is "
            "applied before the cost gate."
        ),
    }

    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")

    if not report["within_budget"]:
        print(
            "LIVE_PROOF_COST_GATE_BLOCKED "
            f"estimated=¥{estimated_cost:.2f} "
            f"max=¥{args.max_estimated_cost_cny:.2f}"
        )
        return 2

    print(
        "LIVE_PROOF_COST_GATE_PASS "
        f"estimated=¥{estimated_cost:.2f} "
        f"max=¥{args.max_estimated_cost_cny:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
