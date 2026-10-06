from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("live proof must be a JSON object")
    return raw


from contextmesh.gate4_reporting import curve_rows, render_markdown


def write_curve_artifacts(proof_path: Path, csv_path: Path, md_path: Path) -> None:
    proof = _load(proof_path)
    rows = curve_rows(proof)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "requested_ratio",
        "actual_ratio",
        "status",
        "selected_blocks",
        "selected_assets",
        "estimated_tokens",
        "contextmesh_evidence_recall",
        "lexical_top_5_evidence_recall",
        "lexical_top_20_evidence_recall",
        "evidence_term_fidelity",
        "negative_accuracy",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    md_path.write_text(render_markdown(proof, rows) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Render Gate 4 scale results as stable CSV and Markdown artifacts.")
    ap.add_argument("--proof", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args = ap.parse_args()
    write_curve_artifacts(args.proof, args.csv, args.markdown)
    print(args.markdown.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
