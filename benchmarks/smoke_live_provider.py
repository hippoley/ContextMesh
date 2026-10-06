from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from contextmesh.provider_smoke import ProviderSmokeError, smoke_openai_compatible


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run two tiny authenticated calls before the full Big Context proof."
    )
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        print(f"PROVIDER_SMOKE_BLOCKED missing environment variable: {args.api_key_env}")
        return 2

    try:
        result = smoke_openai_compatible(
            base_url=args.base_url,
            model=args.model,
            api_key=api_key,
            timeout=args.timeout,
        )
    except ProviderSmokeError as exc:
        payload = {
            "schema_version": 1,
            "status": "failed",
            "model": args.model,
            "base_url": args.base_url,
            "error": str(exc),
            "credential_material_recorded": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        print("PROVIDER_SMOKE_FAIL")
        return 3

    payload = result.as_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    print("PROVIDER_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
