from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field

from .judges import OpenAICompatibleJudge
from .store import FileContextStore


class NeedleProbe(BaseModel):
    asset: str
    needle: str


class NeedleProbeResult(BaseModel):
    asset: str
    needle: str
    matched: bool = False
    inspected_blocks: int = 0
    unsupported_blocks: int = 0
    evidence_notes: list[str] = Field(default_factory=list)


class LiveFidelityReport(BaseModel):
    corpus_id: str
    passed: bool
    route_id: str | None = None
    results: list[NeedleProbeResult]


def run_live_needles(
    store: FileContextStore,
    corpus_id: str,
    judge: OpenAICompatibleJudge,
    probes: list[NeedleProbe],
) -> LiveFidelityReport:
    """Run model-level needle recovery against actual required blocks.

    Unlike retrieval tests, every block belonging to the target asset is inspected.
    A probe passes only when the model echoes the exact marker from at least one block.
    Unsupported modality blocks are recorded explicitly rather than skipped silently.
    """
    manifest = store.get_manifest(corpus_id)
    blocks = [store.get_block(corpus_id, x) for x in manifest.coverage_ids()]
    results: list[NeedleProbeResult] = []

    for probe in probes:
        target = [b for b in blocks if Path(b.source.path).name == Path(probe.asset).name]
        out = NeedleProbeResult(asset=probe.asset, needle=probe.needle)
        question = (
            f'Fidelity probe: determine whether the CURRENT source block contains, displays, or audibly says the exact marker '
            f'"{probe.needle}". If present, set relevant=true and echo the marker exactly in note. If absent, relevant=false.'
        )
        for block in target:
            if not judge.can_inspect(block):
                out.unsupported_blocks += 1
                continue
            out.inspected_blocks += 1
            note, relevant = judge.inspect(question, probe.needle, block, [])
            if note:
                out.evidence_notes.append(note[:1000])
            if relevant and probe.needle.lower() in (note or "").lower():
                out.matched = True
        results.append(out)

    return LiveFidelityReport(
        corpus_id=corpus_id,
        route_id=judge.route_id,
        passed=bool(results) and all(x.matched and x.unsupported_blocks == 0 for x in results),
        results=results,
    )
