from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .reader import CorpusReader
from .rlm_tools import ReaderSession
from .store import FileContextStore


@dataclass
class RLMToolBundle:
    """Portable tool bundle for the official `rlms` package.

    ContextMesh remains the source of truth for corpus addressing and coverage.
    RLM is an optional reasoning harness on top. The bundle deliberately exposes
    `coverage()` and `next_unvisited()` so an RLM policy can prove it has traversed
    every required block rather than stopping after retrieval hits.
    """

    session: ReaderSession

    def custom_tools(self) -> dict[str, Any]:
        return {
            "cm_manifest": {
                "tool": self.session.manifest,
                "description": "Return corpus roots, warnings, and required full-coverage block count.",
            },
            "cm_read": {
                "tool": self.session.read,
                "description": "Read one addressable context block by id. Reading a required block marks it visited.",
            },
            "cm_parent": {
                "tool": self.session.parent,
                "description": "Read the structural parent of a block.",
            },
            "cm_children": {
                "tool": self.session.children,
                "description": "List/read structural children of a block.",
            },
            "cm_neighbors": {
                "tool": self.session.neighbors,
                "description": "Read previous/current/next blocks without changing eligibility of any block.",
            },
            "cm_read_range": {
                "tool": self.session.read_range,
                "description": "Read a local sibling window around one block and mark required blocks in that window visited.",
            },
            "cm_search": {
                "tool": self.session.search,
                "description": "Navigation-only lexical ranking. Results change read order, never full-coverage eligibility.",
            },
            "cm_next_unvisited": {
                "tool": self.session.next_unvisited,
                "description": "Return the next required block that has not yet been read. Authoritative for full coverage.",
            },
            "cm_coverage": {
                "tool": self.session.coverage,
                "description": "Return visited/required counts. A full-coverage workflow must reach complete=true before final scoring.",
            },
        }

    def context_descriptor(self, question: str, answer: str) -> dict[str, Any]:
        return {
            "task": "full_coverage_evaluation",
            "question": question,
            "candidate_answer": answer,
            "corpus": self.session.manifest(),
            "contract": {
                "retrieval_is_scheduling_only": True,
                "final_score_requires_coverage": 1.0,
            },
        }


def build_rlm_tool_bundle(store: FileContextStore, corpus_id: str) -> RLMToolBundle:
    return RLMToolBundle(ReaderSession(CorpusReader(store, corpus_id)))


def create_official_rlm(
    bundle: RLMToolBundle,
    *,
    backend: str,
    backend_kwargs: dict[str, Any],
    **kwargs: Any,
):
    """Instantiate the official alexzhang13/rlm package when installed.

    `pip install rlms` provides `from rlm import RLM`. This function is optional and
    raises a clear error rather than making ContextMesh itself depend on RLM.
    """
    try:
        from rlm import RLM  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Official RLM runtime is not installed. Install contextmesh[rlm] / `pip install rlms`.") from exc

    system = kwargs.pop(
        "custom_system_prompt",
        """You are running a full-coverage corpus evaluation. Use the ContextMesh cm_* tools to inspect the corpus.\n"
        "Search is navigation only. Before producing any final evaluation, call cm_coverage() and continue with "
        "cm_next_unvisited() until complete=true. Preserve contradictions, exceptions, numbers, dates and source ids.""",
    )
    return RLM(
        backend=backend,
        backend_kwargs=backend_kwargs,
        custom_tools=bundle.custom_tools(),
        custom_system_prompt=system,
        **kwargs,
    )
