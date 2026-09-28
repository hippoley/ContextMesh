from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

from contextmesh.big_context_proof import (
    CorpusPosition,
    Gate1CorpusSpec,
    Gate2NeedleSpec,
    LocalPosition,
    NeedleCase,
    NeedleKind,
    TaskCase,
    evaluate_gate1_corpus,
    validate_needle_matrix,
    write_proof_artifact,
)
from contextmesh.ingest import ingest_paths
from contextmesh.models import ContextBlock, Modality
from contextmesh.store import FileContextStore


MONTH_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}(?:,\s*|\s+)\d{4}\b|\b(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?(?:%|x)?\b", re.IGNORECASE)
EXCEPTION_RE = re.compile(
    r"\b(?:unless|except|exception|however|subject to|may not|must not|not required|only if|provided that)\b",
    re.IGNORECASE,
)
SUPERSESSION_RE = re.compile(
    r"\b(?:version|revision|revised|updated|update|current|supersed|replace|amendment|transition)\w*\b",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")

STOP = {
    "this", "that", "with", "from", "have", "will", "shall", "must", "should",
    "into", "their", "there", "which", "these", "those", "they", "them", "were",
    "been", "being", "also", "such", "than", "when", "where", "what", "about",
    "using", "used", "use", "system", "systems", "nist", "framework", "risk",
}


def _load_spec(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not raw.get("sources"):
        raise ValueError("corpus spec has no sources")
    return raw


def _download(url: str, target: Path, attempts: int = 4) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "ContextMesh-BigContextProof/1.0 (+https://github.com/hippoley/ContextMesh)",
                    "Accept": "*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=90) as response:
                data = response.read()
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type", "")
            if not data:
                raise RuntimeError("download returned an empty body")
            target.write_bytes(data)
            return {
                "name": target.name,
                "url": url,
                "final_url": final_url,
                "content_type": content_type,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"failed to download {url}: {last}")


def _clean(text: str) -> str:
    return " ".join((text or "").replace("\u00ad", "").split())


def _sentences(text: str) -> list[str]:
    cleaned = (text or "").replace("\u00ad", "")
    out = []
    for raw in SENTENCE_RE.split(cleaned):
        sentence = _clean(raw)
        if 60 <= len(sentence) <= 700 and len(sentence.split()) >= 8:
            out.append(sentence)
    return out


def _phrase(sentence: str, words: int = 12) -> str:
    tokens = sentence.split()
    if len(tokens) <= words:
        return sentence
    start = max(0, (len(tokens) - words) // 2)
    return " ".join(tokens[start : start + words]).strip(" ,;:()[]")


def _keywords(sentence: str, n: int = 3) -> list[str]:
    words = [
        word.lower()
        for word in WORD_RE.findall(sentence)
        if word.lower() not in STOP
    ]
    unique = []
    for word in sorted(words, key=lambda x: (-len(x), x)):
        if word not in unique:
            unique.append(word)
        if len(unique) >= n:
            break
    return unique


def _position(index: int, total: int, enum_cls):
    if total <= 1:
        return list(enum_cls)[1]
    ratio = index / max(1, total - 1)
    if ratio < 1 / 3:
        return list(enum_cls)[0]
    if ratio < 2 / 3:
        return list(enum_cls)[1]
    return list(enum_cls)[2]


def _block_positions(
    manifest,
    blocks: list[ContextBlock],
) -> dict[str, tuple[CorpusPosition, LocalPosition]]:
    asset_order = {Path(path).name: i for i, path in enumerate(manifest.assets)}
    by_asset: dict[str, list[ContextBlock]] = defaultdict(list)
    for block in blocks:
        by_asset[Path(block.source.path).name].append(block)

    positions = {}
    for asset, group in by_asset.items():
        group.sort(key=lambda block: manifest.coverage_ids().index(block.id))
        aidx = asset_order.get(asset, 0)
        cpos = _position(aidx, len(manifest.assets), CorpusPosition)
        for idx, block in enumerate(group):
            lpos = _position(idx, len(group), LocalPosition)
            positions[block.id] = (cpos, lpos)
    return positions


def _eligible_sentences(
    blocks: list[ContextBlock],
    *,
    modality: Modality | None = None,
    pattern: re.Pattern | None = None,
) -> list[tuple[ContextBlock, str]]:
    out = []
    for block in blocks:
        if modality is not None and block.modality != modality:
            continue
        for sentence in _sentences(block.text):
            if pattern is not None and not pattern.search(sentence):
                continue
            out.append((block, sentence))
    return out


def _case(
    case_id: str,
    kind: NeedleKind,
    block: ContextBlock,
    sentence: str,
    positions: dict[str, tuple[CorpusPosition, LocalPosition]],
    *,
    question: str,
    match_terms: list[str],
    modality: Modality | None = None,
    tags: list[str] | None = None,
) -> NeedleCase:
    cpos, lpos = positions[block.id]
    return NeedleCase(
        id=case_id,
        kind=kind,
        question=question,
        target_assets=[Path(block.source.path).name],
        expected_present=True,
        expected_answer=sentence,
        match_terms=match_terms,
        corpus_position=cpos,
        local_position=lpos,
        modality=modality or block.modality,
        tags=tags or [],
    )


def _take_diverse(
    pool: list[tuple[ContextBlock, str]],
    count: int,
) -> list[tuple[ContextBlock, str]]:
    if not pool:
        return []
    by_asset: dict[str, list[tuple[ContextBlock, str]]] = defaultdict(list)
    for item in pool:
        by_asset[Path(item[0].source.path).name].append(item)
    for group in by_asset.values():
        group.sort(key=lambda item: (item[0].id, item[1]))
    assets = sorted(by_asset)
    out = []
    cursor = 0
    while len(out) < count and any(by_asset.values()):
        asset = assets[cursor % len(assets)]
        if by_asset[asset]:
            out.append(by_asset[asset].pop(0))
        cursor += 1
        if cursor > count * max(4, len(assets)) and len(out) < count:
            break
    return out


def _build_matrix(store: FileContextStore, corpus_id: str) -> list[NeedleCase]:
    manifest = store.get_manifest(corpus_id)
    blocks = [store.get_block(corpus_id, bid) for bid in manifest.coverage_ids()]
    positions = _block_positions(manifest, blocks)
    text_pool = _eligible_sentences(blocks, modality=Modality.TEXT)
    table_blocks = [block for block in blocks if block.modality == Modality.TABLE and _clean(block.text)]
    cases: list[NeedleCase] = []

    # Exact wording — source phrase is scored after execution; the prompt only gets keywords.
    for idx, (block, sentence) in enumerate(_take_diverse(text_pool, 15)):
        phrase = _phrase(sentence, 11)
        kws = _keywords(sentence, 2)
        cases.append(
            _case(
                f"exact-{idx:03d}",
                NeedleKind.EXACT,
                block,
                phrase,
                positions,
                question=f"Locate the exact source wording about {' and '.join(kws) or 'this topic'}.",
                match_terms=[phrase],
                tags=["exact"],
            )
        )

    # Semantic paraphrase — question uses only extracted topical keywords, not the target wording.
    semantic_pool = _take_diverse(text_pool[20:] + text_pool[:20], 15)
    for idx, (block, sentence) in enumerate(semantic_pool):
        phrase = _phrase(sentence, 10)
        kws = _keywords(sentence, 3)
        cases.append(
            _case(
                f"semantic-{idx:03d}",
                NeedleKind.SEMANTIC_PARAPHRASE,
                block,
                phrase,
                positions,
                question=f"What guidance does the source provide concerning {', '.join(kws) or 'the relevant topic'}?",
                match_terms=[phrase],
                tags=["semantic"],
            )
        )

    for idx, (block, sentence) in enumerate(
        _take_diverse(_eligible_sentences(blocks, modality=Modality.TEXT, pattern=NUMBER_RE), 10)
    ):
        match = NUMBER_RE.search(sentence)
        number = match.group(0) if match else _phrase(sentence, 4)
        phrase = _phrase(sentence, 12)
        cases.append(
            _case(
                f"number-{idx:03d}",
                NeedleKind.NUMBER,
                block,
                phrase,
                positions,
                question="What numeric value or numbered requirement is stated in the relevant source?",
                match_terms=[number, phrase],
                tags=["number"],
            )
        )

    for idx, (block, sentence) in enumerate(
        _take_diverse(_eligible_sentences(blocks, modality=Modality.TEXT, pattern=MONTH_RE), 10)
    ):
        match = MONTH_RE.search(sentence)
        date = match.group(0) if match else _phrase(sentence, 4)
        cases.append(
            _case(
                f"date-{idx:03d}",
                NeedleKind.DATE,
                block,
                sentence,
                positions,
                question="What date or year is tied to the relevant source statement?",
                match_terms=[date],
                tags=["date"],
            )
        )

    for idx, (block, sentence) in enumerate(
        _take_diverse(_eligible_sentences(blocks, modality=Modality.TEXT, pattern=EXCEPTION_RE), 15)
    ):
        phrase = _phrase(sentence, 12)
        cases.append(
            _case(
                f"exception-{idx:03d}",
                NeedleKind.EXCEPTION,
                block,
                phrase,
                positions,
                question="What exception, limitation, or conditional language changes the general rule?",
                match_terms=[phrase],
                tags=["exception"],
            )
        )

    # Contradiction cases ask for evidence that would be required to reject the opposite claim.
    for idx, (block, sentence) in enumerate(_take_diverse(text_pool[40:] + text_pool[:40], 10)):
        phrase = _phrase(sentence, 10)
        kws = _keywords(sentence, 2)
        cases.append(
            _case(
                f"contradiction-{idx:03d}",
                NeedleKind.CONTRADICTION,
                block,
                phrase,
                positions,
                question=f"What source evidence should be consulted before accepting a contrary claim about {' and '.join(kws) or 'this issue'}?",
                match_terms=[phrase],
                tags=["contradiction"],
            )
        )

    for idx, (block, sentence) in enumerate(
        _take_diverse(_eligible_sentences(blocks, modality=Modality.TEXT, pattern=SUPERSESSION_RE), 10)
    ):
        phrase = _phrase(sentence, 12)
        cases.append(
            _case(
                f"supersession-{idx:03d}",
                NeedleKind.SUPERSESSION,
                block,
                phrase,
                positions,
                question="What version, revision, update, or transition statement controls interpretation of the source?",
                match_terms=[phrase],
                tags=["supersession", "authority"],
            )
        )

    # Cross-file cases use naturally recurring governance/security terms and require
    # relevant evidence from two different real assets.
    common_terms = [
        "risk management",
        "artificial intelligence",
        "security controls",
        "incident response",
        "privacy",
        "governance",
        "monitoring",
        "documentation",
        "risk assessment",
        "supply chain",
    ]
    by_term: dict[str, dict[str, ContextBlock]] = {}
    for term in common_terms:
        assets: dict[str, ContextBlock] = {}
        for block in blocks:
            if term in _clean(block.text).lower():
                assets.setdefault(Path(block.source.path).name, block)
        by_term[term] = assets

    cross_idx = 0
    for term in common_terms:
        assets = sorted(by_term[term])
        if len(assets) < 2:
            continue
        a, b = assets[0], assets[-1]
        block_a = by_term[term][a]
        block_b = by_term[term][b]
        cpos = positions[block_a.id][0]
        lpos = positions[block_a.id][1]
        cases.append(
            NeedleCase(
                id=f"cross-file-{cross_idx:03d}",
                kind=NeedleKind.CROSS_FILE,
                question=f"How is {term} addressed across the corpus rather than in only one source?",
                target_assets=[a, b],
                expected_present=True,
                expected_answer=f"Both {a} and {b} contain source evidence about {term}.",
                match_terms=[term],
                required_asset_hits=2,
                corpus_position=cpos,
                local_position=lpos,
                modality=Modality.TEXT,
                tags=["cross-file"],
            )
        )
        cross_idx += 1
        if cross_idx >= 10:
            break

    # Table-cell fidelity uses real CSV/XLSX rows.
    table_candidates: list[tuple[ContextBlock, str]] = []
    for block in table_blocks:
        for line in (block.text or "").splitlines():
            clean = _clean(line)
            if len(clean) >= 20 and ("\t" in line or "," in line or len(clean.split()) >= 4):
                table_candidates.append((block, clean))
    for idx, (block, line) in enumerate(_take_diverse(table_candidates, 15)):
        cells = [cell.strip() for cell in re.split(r"\t+|,\s*", line) if cell.strip()]
        distinctive = max(cells, key=len) if cells else _phrase(line, 8)
        if len(distinctive) > 120:
            distinctive = _phrase(distinctive, 10)
        cases.append(
            _case(
                f"table-{idx:03d}",
                NeedleKind.TABLE_CELL,
                block,
                line,
                positions,
                question="Which table row or cell contains the requested governance/control information?",
                match_terms=[distinctive],
                modality=Modality.TABLE,
                tags=["table"],
            )
        )

    # Image-text fidelity: pair a rendered PDF visual page with the independent
    # text channel from the same real page. The model-facing case targets the image
    # block; the text channel supplies scorer-only ground truth for the wording.
    text_by_page: dict[tuple[str, int], list[tuple[ContextBlock, str]]] = defaultdict(list)
    image_by_page: dict[tuple[str, int], ContextBlock] = {}
    for block in blocks:
        page = block.source.locator.get("page")
        if not isinstance(page, int):
            continue
        key = (Path(block.source.path).name, page)
        channel = str(block.source.locator.get("channel") or "")
        if block.modality == Modality.TEXT and channel == "text":
            for sentence in _sentences(block.text):
                text_by_page[key].append((block, sentence))
        elif block.modality == Modality.IMAGE and channel == "visual":
            image_by_page[key] = block

    image_candidates: list[tuple[ContextBlock, str]] = []
    for key in sorted(set(text_by_page) & set(image_by_page)):
        visual = image_by_page[key]
        sentences = text_by_page[key]
        if not sentences:
            continue
        # Use a source sentence with enough distinctive terms to make the visual
        # assertion falsifiable without exposing the sentence itself in the question.
        best = max(sentences, key=lambda item: len(_keywords(item[1], 4)))[1]
        phrase = _phrase(best, 10)
        if len(phrase) >= 40 and len(_keywords(best, 2)) >= 2:
            image_candidates.append((visual, best))

    for idx, (block, sentence) in enumerate(_take_diverse(image_candidates, 12)):
        phrase = _phrase(sentence, 10)
        kws = _keywords(sentence, 3)
        cases.append(
            _case(
                f"image-text-{idx:03d}",
                NeedleKind.IMAGE_TEXT,
                block,
                phrase,
                positions,
                question=(
                    "Read the rendered source page and locate the wording concerning "
                    f"{', '.join(kws) or 'the relevant topic'}."
                ),
                match_terms=[phrase],
                modality=Modality.IMAGE,
                tags=["vision", "image-text"],
            )
        )

    # Negative probes are fixed absent markers and have no oracle asset.
    for idx in range(10):
        marker = f"CONTEXTMESH_NIST_ABSENT_{idx:03d}_ZXQ"
        cases.append(
            NeedleCase(
                id=f"negative-{idx:03d}",
                kind=NeedleKind.NEGATIVE,
                question=f"Does any source contain the exact marker {marker}?",
                target_assets=[],
                expected_present=False,
                expected_answer="No.",
                match_terms=[marker],
                corpus_position=[CorpusPosition.EARLY, CorpusPosition.MIDDLE, CorpusPosition.LATE][idx % 3],
                local_position=[LocalPosition.HEAD, LocalPosition.MIDDLE, LocalPosition.TAIL][idx % 3],
                modality=Modality.TEXT,
                tags=["negative"],
            )
        )

    # The corpus is large enough that some specialized pools can vary by upstream
    # release. Preserve the required taxonomy and fill only with additional exact
    # real-source cases if total count is below 120. Image-text cases are never
    # synthesized by this fallback: if the visual pool is unavailable, Gate 2 should
    # expose that loss rather than turn text evidence into fake vision coverage.
    if len(cases) < 120:
        existing = {case.match_terms[0] for case in cases if case.match_terms}
        for block, sentence in _take_diverse(text_pool, 200):
            phrase = _phrase(sentence, 12)
            if phrase in existing:
                continue
            idx = len(cases)
            cases.append(
                _case(
                    f"exact-fill-{idx:03d}",
                    NeedleKind.EXACT,
                    block,
                    phrase,
                    positions,
                    question="Locate the source wording that supports this benchmark item.",
                    match_terms=[phrase],
                    tags=["exact", "fill"],
                )
            )
            existing.add(phrase)
            if len(cases) >= 120:
                break

    return cases


def _build_tasks(cases: list[NeedleCase]) -> list[TaskCase]:
    positives = [case for case in cases if case.expected_present and case.expected_answer]
    negatives = [case for case in cases if not case.expected_present]
    tasks: list[TaskCase] = []

    # Supported answers from diverse kinds.
    seen_kinds = set()
    selected = []
    for case in positives:
        if case.kind not in seen_kinds:
            selected.append(case)
            seen_kinds.add(case.kind)
    for case in positives:
        if case not in selected:
            selected.append(case)
        if len(selected) >= 18:
            break

    for case in selected[:18]:
        tags = [case.kind.value, case.modality.value, *case.tags]
        tasks.append(
            TaskCase(
                id=f"supported-{case.id}",
                question=case.question,
                candidate_answer=case.expected_answer or "",
                expected_min_score=70,
                tags=sorted(set(tags)),
            )
        )

    # Deliberately unsupported claims over the same questions.
    for case in selected[:10]:
        tags = [case.kind.value, "counterclaim", *case.tags]
        tasks.append(
            TaskCase(
                id=f"rejected-{case.id}",
                question=case.question,
                candidate_answer=(
                    "The cited source contains no such rule or evidence, and the opposite "
                    "conclusion should be accepted without qualification."
                ),
                expected_max_score=30,
                tags=sorted(set(tags)),
            )
        )

    for case in negatives[:5]:
        marker = case.match_terms[0]
        tasks.append(
            TaskCase(
                id=f"negative-false-{case.id}",
                question=case.question,
                candidate_answer=f"Yes. The corpus explicitly contains {marker}.",
                expected_max_score=30,
                tags=["negative"],
            )
        )
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--spec",
        type=Path,
        default=Path("benchmarks/big-context/nist-public-corpus.json"),
    )
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--model-context-tokens", type=int, default=128_000)
    ap.add_argument("--min-corpus-ratio", type=float, default=5.0)
    args = ap.parse_args()

    spec = _load_spec(args.spec)
    downloads = args.workdir / "downloads"
    store_root = args.workdir / "store"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    download_records = []
    paths = []
    for source in spec["sources"]:
        target = downloads / source["name"]
        record = _download(source["url"], target)
        record["declared_family"] = source.get("family")
        download_records.append(record)
        paths.append(target)
        print(
            f"DOWNLOADED {target.name} bytes={record['size_bytes']} "
            f"sha256={record['sha256'][:16]}..."
        )

    store = FileContextStore(store_root)
    manifest = ingest_paths(
        paths,
        store,
        spec.get("corpus_id", "nist-public-big-context-v1"),
        window_chars=12_000,
        overlap_chars=800,
    )
    write_proof_artifact(args.output_dir / "download-manifest.json", {"sources": download_records})
    write_proof_artifact(args.output_dir / "corpus-manifest.json", manifest)

    gate1 = evaluate_gate1_corpus(
        manifest,
        Gate1CorpusSpec(
            min_assets=10,
            max_assets=30,
            min_format_families=3,
            min_corpus_to_context_ratio=args.min_corpus_ratio,
            model_context_tokens=args.model_context_tokens,
        ),
    )
    write_proof_artifact(args.output_dir / "gate1.json", gate1)
    print(
        f"GATE1 status={gate1.status} assets={gate1.assets} "
        f"ratio={gate1.corpus_to_context_ratio:.3f} "
        f"families={gate1.format_families} semantic={gate1.semantic_coverage:.3f}"
    )

    cases = _build_matrix(store, manifest.corpus_id)
    gate2 = validate_needle_matrix(
        cases,
        Gate2NeedleSpec(
            min_cases=100,
            min_kinds=8,
            min_modalities=2,
        ),
        manifest=manifest,
    )
    write_proof_artifact(
        args.output_dir / "needle-matrix.json",
        {"corpus_id": manifest.corpus_id, "cases": [case.model_dump(mode="json") for case in cases]},
    )
    write_proof_artifact(args.output_dir / "gate2.json", gate2)
    print(
        f"GATE2 status={gate2.status} cases={gate2.total_cases} "
        f"kinds={len(gate2.kind_counts)} modalities={gate2.modality_counts}"
    )

    tasks = _build_tasks(cases)
    write_proof_artifact(
        args.output_dir / "task-cases.json",
        {"corpus_id": manifest.corpus_id, "cases": [case.model_dump(mode="json") for case in tasks]},
    )
    print(f"TASK_SET cases={len(tasks)}")

    if gate1.status != "pass" or gate2.status != "pass":
        print("PUBLIC_PROOF_PREFLIGHT_FAIL")
        return 2
    print("PUBLIC_PROOF_PREFLIGHT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
