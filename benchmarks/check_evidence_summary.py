from __future__ import annotations

import argparse
import json
from pathlib import Path

from contextmesh.evidence_consumer import evidence_check


def main() -> int:
    ap = argparse.ArgumentParser(description="Consume evidence-summary.json without re-judging proof policy.")
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--fail-on-hold", action="store_true")
    args = ap.parse_args()
    summary = None
    if args.summary.is_file():
        raw = json.loads(args.summary.read_text(encoding="utf-8"))
        summary = raw if isinstance(raw, dict) else None
    result = evidence_check(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if args.fail_on_hold and result["decision"] == "hold" else 0


if __name__ == "__main__":
    raise SystemExit(main())
