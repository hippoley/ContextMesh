from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_FILES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs" / "reality" / "README.md",
    ROOT / "site" / "README.md",
    ROOT / "site" / "reality.html",
]

GENERATED_PUBLIC_PATHS = {
    (ROOT / "site" / "reality-data.json").resolve(),
}

MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
HTML_ATTR = re.compile(r"""(?:href|src)=["']([^"']+)["']""", re.IGNORECASE)


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    # Markdown can include an optional title after whitespace.
    if " " in target and not target.startswith(("http://", "https://")):
        target = target.split(" ", 1)[0]
    return unquote(target)


def is_external(target: str) -> bool:
    return target.startswith(
        ("http://", "https://", "mailto:", "tel:", "data:", "javascript:")
    )


def check_file(path: Path) -> list[str]:
    if not path.exists():
        return [f"{path.relative_to(ROOT)}: file itself is missing"]

    text = path.read_text(encoding="utf-8")
    targets = [*MARKDOWN_LINK.findall(text), *HTML_ATTR.findall(text)]
    failures: list[str] = []

    for raw in targets:
        target = normalize_target(raw)
        if not target or target.startswith("#") or is_external(target):
            continue

        clean = target.split("#", 1)[0].split("?", 1)[0]
        if not clean:
            continue

        # Site-only generated artifact.
        if path == ROOT / "site" / "reality.html" and clean == "./reality-data.json":
            resolved = (path.parent / clean).resolve()
            if resolved in GENERATED_PUBLIC_PATHS:
                continue

        resolved = (path.parent / clean).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            failures.append(
                f"{path.relative_to(ROOT)} -> {target}: escapes repository root"
            )
            continue

        if not resolved.exists():
            failures.append(
                f"{path.relative_to(ROOT)} -> {target}: missing {resolved.relative_to(ROOT)}"
            )

    return failures


def main() -> None:
    failures: list[str] = []
    for path in PUBLIC_FILES:
        failures.extend(check_file(path))

    if failures:
        print("PUBLIC_LINK_CHECK_FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print(
        "PUBLIC_LINK_CHECK_OK "
        f"files={len(PUBLIC_FILES)} generated_allowlist={len(GENERATED_PUBLIC_PATHS)}"
    )


if __name__ == "__main__":
    main()
