from __future__ import annotations

import re
import struct
from pathlib import Path

from build_reality_manifest import build_manifest

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "site" / "reality.html"
PREVIEW_PATH = ROOT / "assets" / "contextmesh-social-preview.png"


def fail(message: str) -> None:
    raise SystemExit(f"PUBLIC_SITE_CHECK_FAILED: {message}")


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"{path} is not a PNG")
    if data[12:16] != b"IHDR":
        fail(f"{path} has no PNG IHDR header")
    return struct.unpack(">II", data[16:24])


def main() -> None:
    if not HTML_PATH.exists():
        fail("site/reality.html is missing")
    if not PREVIEW_PATH.exists():
        fail("assets/contextmesh-social-preview.png is missing")

    html = HTML_PATH.read_text(encoding="utf-8")
    manifest = build_manifest()

    forbidden = {
        "./admin.html": "backend Admin link",
        "./api.html": "backend API link",
        ">Workspace<": "backend Workspace nav",
    }
    for needle, label in forbidden.items():
        if needle in html:
            fail(f"public Reality Lab contains {label}: {needle}")

    singleton_patterns = {
        "canonical": r'<link\s+rel="canonical"\s+href="[^"]+"\s*/?>',
        "og:title": r'<meta\s+property="og:title"\s+content="[^"]+"\s*/?>',
        "og:description": r'<meta\s+property="og:description"\s+content="[^"]+"\s*/?>',
        "og:type": r'<meta\s+property="og:type"\s+content="[^"]+"\s*/?>',
        "og:url": r'<meta\s+property="og:url"\s+content="[^"]+"\s*/?>',
        "og:image": r'<meta\s+property="og:image"\s+content="[^"]+"\s*/?>',
    }
    for label, pattern in singleton_patterns.items():
        count = len(re.findall(pattern, html))
        if count != 1:
            fail(f"{label} must appear exactly once, found {count}")

    expected_public_root = "https://hippoley.github.io/ContextMesh/"
    if f'<link rel="canonical" href="{expected_public_root}"/>' not in html:
        fail("canonical URL is not the public Pages root")
    if f'<meta property="og:url" content="{expected_public_root}"/>' not in html:
        fail("og:url is not the public Pages root")
    if "assets/contextmesh-social-preview.png" not in html:
        fail("OpenGraph/Twitter metadata does not reference the raster preview")
    if 'fetch("./reality-data.json"' not in html:
        fail("public Reality Lab is not hydrating from the generated evidence manifest")
    if 'href="./reality-data.json"' not in html:
        fail("public Reality Lab does not expose its machine-readable manifest")

    ids = re.findall(r'\sid="([^"]+)"', html)
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        fail(f"duplicate HTML ids: {duplicates}")

    expected_cases = {"case-cognee", "case-ragflow", "case-dify", "case-mem0"}
    if set(manifest.get("sources", {})) != {"cognee", "ragflow", "dify", "mem0"}:
        fail("Reality manifest is missing source provenance records")
    for key, source in manifest["sources"].items():
        if len(source.get("sha256", "")) != 64:
            fail(f"Reality manifest source {key} has no SHA-256 provenance")

    manifest_cases = {f"case-{key}" for key in manifest["cases"]}
    if manifest_cases != expected_cases:
        fail(f"manifest/UI case mismatch: {sorted(manifest_cases)}")
    case_ids = {value for value in ids if value.startswith("case-")}
    if case_ids != expected_cases:
        fail(f"unexpected Reality case ids: {sorted(case_ids)}")

    if html.count('class="share-case"') != len(expected_cases):
        fail("every Reality case must have one Copy link control")
    if html.count('>run ↗</a>') != len(expected_cases):
        fail("every Reality case must link to an executable run")
    if html.count('>evidence ↗</a>') != len(expected_cases):
        fail("every Reality case must link to evidence")

    for section in ("cases", "lifecycle", "timeline"):
        if f'id="{section}"' not in html:
            fail(f"public navigation target #{section} is missing")

    width, height = png_dimensions(PREVIEW_PATH)
    if (width, height) != (1280, 640):
        fail(f"social preview must be 1280x640, found {width}x{height}")

    print(
        "PUBLIC_SITE_CHECK_OK "
        f"cases={len(expected_cases)} preview={width}x{height} "
        f"verified_through={manifest['verified_through']} "
        "runtime_links=0 metadata_singletons=ok evidence_manifest=ok"
    )


if __name__ == "__main__":
    main()
