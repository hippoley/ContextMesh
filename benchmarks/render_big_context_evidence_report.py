from __future__ import annotations

import argparse
import json
from pathlib import Path

from contextmesh.evidence_reporting import build_evidence_report, build_evidence_summary


def _load(path: Path | None):
    if path is None or not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render a reviewer-facing index of big-context proof evidence."
    )
    ap.add_argument("--live-proof", type=Path, required=True)
    ap.add_argument("--gate5-diff", type=Path)
    ap.add_argument("--markdown", type=Path, required=True)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()

    live = _load(args.live_proof)
    gate5 = _load(args.gate5_diff)
    text = build_evidence_report(live, gate5)
    summary = build_evidence_summary(live, gate5)

    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(text + "\n", encoding="utf-8")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
