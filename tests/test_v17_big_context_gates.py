from pathlib import Path

from contextmesh.big_context_proof import (
    CorpusPosition,
    Gate1CorpusSpec,
    Gate2NeedleSpec,
    LocalPosition,
    NeedleCase,
    NeedleKind,
    evaluate_gate1_corpus,
    validate_needle_matrix,
)
from contextmesh.ingest import ingest_paths
from contextmesh.models import Modality
from contextmesh.store import FileContextStore


def _realish_corpus(tmp_path: Path):
    paths = []
    for i in range(4):
        p = tmp_path / f"policy-{i}.txt"
        p.write_text(("policy clause and exception " * 120) + f"needle-{i}", encoding="utf-8")
        paths.append(p)
    for i in range(3):
        p = tmp_path / f"record-{i}.json"
        p.write_text('{"status":"active","detail":"' + ("x" * 3200) + '"}', encoding="utf-8")
        paths.append(p)
    for i in range(3):
        p = tmp_path / f"table-{i}.csv"
        p.write_text("key,value\n" + "\n".join(f"k{j},v{j}" for j in range(500)), encoding="utf-8")
        paths.append(p)

    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(paths, store, "gate1-realish")
    return store, manifest


def test_gate1_requires_real_asset_count_hashes_formats_and_over_context_ratio(tmp_path: Path):
    _, manifest = _realish_corpus(tmp_path)
    report = evaluate_gate1_corpus(
        manifest,
        Gate1CorpusSpec(
            min_assets=10,
            max_assets=30,
            min_format_families=2,
            model_context_tokens=1000,
            min_corpus_to_context_ratio=5.0,
        ),
    )

    assert report.status == "pass"
    assert report.assets == 10
    assert report.source_hash_coverage == 1.0
    assert set(report.format_families) >= {"text", "table"}
    assert report.corpus_to_context_ratio >= 5.0


def test_gate1_fails_when_corpus_does_not_qualify(tmp_path: Path):
    p = tmp_path / "only.txt"
    p.write_text("tiny corpus", encoding="utf-8")
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths([p], store, "too-small")

    report = evaluate_gate1_corpus(
        manifest,
        Gate1CorpusSpec(
            min_assets=10,
            max_assets=30,
            min_format_families=3,
            model_context_tokens=128000,
            min_corpus_to_context_ratio=5.0,
        ),
    )

    assert report.status == "fail"
    assert any(x.startswith("assets:") for x in report.blockers)
    assert any(x.startswith("format-families:") for x in report.blockers)
    assert any(x.startswith("corpus/context-ratio:") for x in report.blockers)


def test_gate2_matrix_requires_kind_and_position_coverage():
    cases = []
    kinds = list(NeedleKind)
    corpus_positions = list(CorpusPosition)
    local_positions = list(LocalPosition)

    for i in range(108):
        kind = kinds[i % len(kinds)]
        cases.append(
            NeedleCase(
                id=f"n-{i:03d}",
                kind=kind,
                question=f"Question {i}",
                target_assets=[f"asset-{i % 12}.txt"],
                expected_present=kind != NeedleKind.NEGATIVE,
                expected_answer=f"answer-{i}",
                match_terms=[f"marker-{i}"],
                corpus_position=corpus_positions[i % len(corpus_positions)],
                local_position=local_positions[(i // len(corpus_positions)) % len(local_positions)],
                modality=[Modality.TEXT, Modality.TABLE, Modality.IMAGE][i % 3],
            )
        )

    report = validate_needle_matrix(cases, Gate2NeedleSpec(min_cases=100, min_kinds=8))

    assert report.status == "pass"
    assert report.total_cases == 108
    assert report.kind_counts["negative"] > 0
    assert report.kind_counts["cross-file"] > 0
    assert set(report.corpus_position_counts) == {"early", "middle", "late"}
    assert set(report.local_position_counts) == {"head", "middle", "tail"}


def test_gate2_rejects_a_large_but_shallow_matrix():
    cases = [
        NeedleCase(
            id=f"exact-{i}",
            kind=NeedleKind.EXACT,
            question="Find marker",
            target_assets=["one.txt"],
            expected_present=True,
            match_terms=[f"m{i}"],
            corpus_position=CorpusPosition.EARLY,
            local_position=LocalPosition.HEAD,
        )
        for i in range(120)
    ]

    report = validate_needle_matrix(cases)

    assert report.status == "fail"
    assert any(x.startswith("needle-kinds:") for x in report.blockers)
    assert "missing-corpus-position:middle" in report.blockers
    assert "missing-local-position:tail" in report.blockers
    assert "missing-kind:negative" in report.blockers
    assert "missing-kind:cross-file" in report.blockers



def test_gate3_runs_needles_over_full_corpus_and_scores_same_model_baselines(tmp_path: Path):
    from contextmesh.big_context_proof import (
        Gate3Spec,
        TaskCase,
        evaluate_gate3,
        run_full_coverage_needles,
        run_task_baselines,
    )
    from contextmesh.models import UsageMetrics

    paths = []
    for i in range(12):
        p = tmp_path / f"doc-{i:02d}.txt"
        marker = ""
        if i == 1:
            marker = " NEEDLE_ALPHA_42 payment deadline is thirty days."
        if i == 10:
            marker = " NEEDLE_OMEGA_77 exception requires sixty days notice."
        p.write_text(("ordinary clause filler " * 80) + marker, encoding="utf-8")
        paths.append(p)

    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(paths, store, "gate3")

    class DeterministicJudge:
        route_id = "deterministic-proof"

        def can_inspect(self, block):
            return True

        def inspect(self, question, answer, block, notes):
            q = question.lower()
            text = block.text.lower()
            relevant = (
                ("alpha" in q and "needle_alpha_42" in text)
                or ("omega" in q and "needle_omega_77" in text)
            )
            if relevant:
                return block.text, True
            return f"{block.id}: inspected; no target fact", False

        def reduce_notes(self, question, answer, notes, level):
            return f"L{level}: {len(notes)} notes"

        def finalize(self, state):
            # Candidate answers used by the task suite contain an explicit expected
            # truth label so the test focuses on baseline orchestration.
            if "correct-answer" in state.answer:
                return 95.0, "supported"
            return 5.0, "unsupported"

        def score_full(self, question, answer, blocks):
            if "correct-answer" in answer:
                return 95.0, "supported"
            return 5.0, "unsupported"

        def usage_snapshot(self):
            return UsageMetrics(route_id=self.route_id)

    cases = [
        NeedleCase(
            id="alpha",
            kind=NeedleKind.EXACT,
            question="Find alpha marker",
            target_assets=["doc-01.txt"],
            expected_present=True,
            expected_answer="NEEDLE_ALPHA_42",
            match_terms=["NEEDLE_ALPHA_42"],
            corpus_position=CorpusPosition.EARLY,
            local_position=LocalPosition.MIDDLE,
        ),
        NeedleCase(
            id="omega",
            kind=NeedleKind.EXCEPTION,
            question="Find omega exception",
            target_assets=["doc-10.txt"],
            expected_present=True,
            expected_answer="NEEDLE_OMEGA_77",
            match_terms=["NEEDLE_OMEGA_77", "sixty days"],
            match_all_terms=True,
            corpus_position=CorpusPosition.LATE,
            local_position=LocalPosition.MIDDLE,
        ),
        NeedleCase(
            id="absent",
            kind=NeedleKind.NEGATIVE,
            question="Find marker NEVER_EXISTS_999",
            target_assets=[],
            expected_present=False,
            expected_answer="NEVER_EXISTS_999",
            match_terms=["NEVER_EXISTS_999"],
            corpus_position=CorpusPosition.MIDDLE,
            local_position=LocalPosition.HEAD,
        ),
    ]

    needle = run_full_coverage_needles(
        store,
        manifest.corpus_id,
        DeterministicJudge,
        cases,
        max_workers=3,
    )

    assert needle.evidence_recall == 1.0
    assert needle.evidence_term_fidelity == 1.0
    assert needle.negative_accuracy == 1.0
    assert needle.unsupported_cases == 0
    assert all(row.visited_blocks == manifest.required_blocks for row in needle.results)
    assert all(row.coverage == 1.0 for row in needle.results)

    tasks = [
        TaskCase(
            id="supported",
            question="Is the candidate supported?",
            candidate_answer="correct-answer",
            expected_min_score=90,
        ),
        TaskCase(
            id="rejected",
            question="Is the candidate supported?",
            candidate_answer="wrong-answer",
            expected_max_score=10,
        ),
    ]
    baselines = run_task_baselines(
        store,
        manifest.corpus_id,
        DeterministicJudge,
        tasks,
        lexical_top_ks=(5, 20),
    )
    by_name = {row.baseline: row for row in baselines}
    assert by_name["contextmesh-full-coverage"].task_accuracy == 1.0
    assert by_name["direct-full-context"].task_accuracy == 1.0
    assert by_name["lexical-top-5"].task_accuracy == 1.0

    gate = evaluate_gate3(
        needle,
        baselines,
        Gate3Spec(
            min_evidence_recall=0.9,
            min_evidence_term_fidelity=0.9,
            min_negative_accuracy=0.9,
            min_task_accuracy=0.9,
        ),
    )
    assert gate.status == "pass"


def test_gate3_fails_when_live_recovery_is_weak():
    from contextmesh.big_context_proof import (
        BaselineSummary,
        Gate3Spec,
        NeedleRecoveryReport,
        NeedleRunResult,
        evaluate_gate3,
    )

    needle = NeedleRecoveryReport(
        corpus_id="c",
        total_cases=2,
        present_cases=2,
        negative_cases=0,
        evidence_recall=0.5,
        evidence_term_fidelity=0.5,
        negative_accuracy=1.0,
        unsupported_cases=0,
        by_kind={"exact": 0.5},
        by_corpus_position={"early": 0.5},
        results=[
            NeedleRunResult(
                case_id="a",
                kind=NeedleKind.EXACT,
                expected_present=True,
                recovered=True,
                term_recall=1.0,
            ),
            NeedleRunResult(
                case_id="b",
                kind=NeedleKind.EXACT,
                expected_present=True,
                recovered=False,
                term_recall=0.0,
            ),
        ],
    )
    baseline = BaselineSummary(
        baseline="contextmesh-full-coverage",
        total_tasks=1,
        completed_tasks=1,
        blocked_tasks=0,
        task_accuracy=1.0,
        latency_seconds=0,
        estimated_cost_usd=0,
        prompt_tokens=0,
        completion_tokens=0,
        results=[],
    )

    gate = evaluate_gate3(needle, [baseline], Gate3Spec())
    assert gate.status == "fail"
    assert any(x.startswith("evidence-recall:") for x in gate.blockers)



def test_gate4_scale_curve_keeps_anchor_evidence_and_grows_distractors(tmp_path: Path):
    from contextmesh.big_context_proof import (
        Gate4Spec,
        TaskCase,
        run_scale_curve,
    )
    from contextmesh.models import UsageMetrics

    paths = []
    for i in range(12):
        p = tmp_path / f"scale-{i:02d}.txt"
        marker = " SCALE_NEEDLE_4242 decisive exception." if i == 10 else ""
        p.write_text(("distractor operational paragraph " * 70) + marker, encoding="utf-8")
        paths.append(p)

    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(paths, store, "scale-source")

    class ScaleJudge:
        route_id = "scale-judge"

        def can_inspect(self, block):
            return True

        def inspect(self, question, answer, block, notes):
            if "scale_needle_4242" in block.text.lower():
                return block.text, True
            return f"{block.id}: inspected", False

        def reduce_notes(self, question, answer, notes, level):
            return f"L{level}: {len(notes)}"

        def finalize(self, state):
            return (95.0, "supported") if "correct-answer" in state.answer else (5.0, "rejected")

        def score_full(self, question, answer, blocks):
            return (95.0, "supported") if "correct-answer" in answer else (5.0, "rejected")

        def usage_snapshot(self):
            return UsageMetrics(route_id=self.route_id)

    needle = NeedleCase(
        id="scale-needle",
        kind=NeedleKind.EXCEPTION,
        question="Find SCALE_NEEDLE_4242",
        target_assets=["scale-10.txt"],
        expected_present=True,
        expected_answer="SCALE_NEEDLE_4242",
        match_terms=["SCALE_NEEDLE_4242"],
        corpus_position=CorpusPosition.LATE,
        local_position=LocalPosition.MIDDLE,
    )
    tasks = [
        TaskCase(
            id="scale-task",
            question="Is the candidate supported?",
            candidate_answer="correct-answer",
            expected_min_score=90,
        )
    ]

    report = run_scale_curve(
        store,
        manifest.corpus_id,
        ScaleJudge,
        [needle],
        tasks,
        Gate4Spec(
            ratios=[1, 2, 5],
            model_context_tokens=3000,
            needle_sample_size=1,
            task_sample_size=1,
            min_evidence_recall=1.0,
            min_task_accuracy=1.0,
            max_recall_drop=0.0,
            required_max_ratio=5.0,
        ),
    )

    assert report.status == "pass"
    assert len(report.points) == 3
    assert all(point.status == "pass" for point in report.points)
    assert all(point.evidence_recall == 1.0 for point in report.points)
    assert all(point.task_accuracy == 1.0 for point in report.points)
    assert report.max_completed_ratio >= 5.0
    assert report.recall_drop == 0.0
    assert report.points[0].selected_blocks < report.points[-1].selected_blocks


def test_gate4_fails_when_source_corpus_cannot_reach_required_ratio(tmp_path: Path):
    from contextmesh.big_context_proof import Gate4Spec, TaskCase, run_scale_curve
    from contextmesh.models import UsageMetrics

    paths = []
    for i in range(3):
        p = tmp_path / f"small-{i}.txt"
        p.write_text(("small " * 100) + (" NEEDLE_SMALL" if i == 2 else ""), encoding="utf-8")
        paths.append(p)
    store = FileContextStore(tmp_path / "store")
    manifest = ingest_paths(paths, store, "small-scale")

    class Judge:
        route_id = "j"
        def can_inspect(self, block): return True
        def inspect(self, question, answer, block, notes):
            return (block.text, "needle_small" in block.text.lower())
        def reduce_notes(self, question, answer, notes, level): return "reduced"
        def finalize(self, state): return 100.0, "ok"
        def score_full(self, question, answer, blocks): return 100.0, "ok"
        def usage_snapshot(self): return UsageMetrics(route_id=self.route_id)

    needle = NeedleCase(
        id="n",
        kind=NeedleKind.EXACT,
        question="find NEEDLE_SMALL",
        target_assets=["small-2.txt"],
        expected_present=True,
        expected_answer="NEEDLE_SMALL",
        match_terms=["NEEDLE_SMALL"],
        corpus_position=CorpusPosition.LATE,
        local_position=LocalPosition.TAIL,
    )
    task = TaskCase(
        id="t",
        question="q",
        candidate_answer="a",
        expected_min_score=90,
    )

    report = run_scale_curve(
        store,
        manifest.corpus_id,
        Judge,
        [needle],
        [task],
        Gate4Spec(
            ratios=[1, 20],
            model_context_tokens=1000,
            needle_sample_size=1,
            task_sample_size=1,
            required_max_ratio=20,
        ),
    )

    assert report.status == "fail"
    assert any("scale-point-blocked:20x" in x for x in report.blockers)


def test_gate5_detects_quality_drift_but_can_leave_cost_as_observational():
    from contextmesh.big_context_proof import (
        Gate5Spec,
        ProofRunSnapshot,
        evaluate_gate5_drift,
    )

    reference = ProofRunSnapshot(
        run_id="r0",
        route_id="route-a",
        model="model-a",
        model_version="2026-09-01",
        prompt_version="p1",
        chunk_policy="12k",
        reducer_policy="typed-0.16",
        evidence_recall=0.96,
        task_accuracy=0.93,
        authority_accuracy=0.98,
        negative_accuracy=1.0,
        estimated_cost_usd=1.0,
        latency_seconds=100,
    )
    safe = ProofRunSnapshot(
        run_id="r1",
        route_id="route-a",
        model="model-a",
        model_version="2026-09-15",
        prompt_version="p2",
        chunk_policy="12k",
        reducer_policy="typed-0.16",
        evidence_recall=0.95,
        task_accuracy=0.92,
        authority_accuracy=0.98,
        negative_accuracy=0.99,
        estimated_cost_usd=2.5,
        latency_seconds=140,
    )

    report = evaluate_gate5_drift(reference, [safe], Gate5Spec())

    assert report.status == "pass"
    assert report.deltas[0].cost_ratio == 2.5
    assert report.deltas[0].latency_ratio == 1.4
    assert report.deltas[0].config_fingerprint != reference.config_fingerprint


def test_gate5_blocks_recall_task_and_authority_regressions():
    from contextmesh.big_context_proof import (
        Gate5Spec,
        ProofRunSnapshot,
        evaluate_gate5_drift,
    )

    reference = ProofRunSnapshot(
        run_id="base",
        route_id="r",
        model="m",
        evidence_recall=0.97,
        task_accuracy=0.94,
        authority_accuracy=0.99,
        negative_accuracy=1.0,
    )
    regressed = ProofRunSnapshot(
        run_id="candidate",
        route_id="r",
        model="m2",
        evidence_recall=0.88,
        task_accuracy=0.82,
        authority_accuracy=0.90,
        negative_accuracy=0.96,
    )

    report = evaluate_gate5_drift(
        reference,
        [regressed],
        Gate5Spec(
            max_evidence_recall_drop=0.05,
            max_task_accuracy_drop=0.05,
            max_authority_accuracy_drop=0.02,
            max_negative_accuracy_drop=0.02,
        ),
    )

    assert report.status == "fail"
    blockers = " ".join(report.blockers)
    assert "evidence-recall-drop" in blockers
    assert "task-accuracy-drop" in blockers
    assert "authority-accuracy-drop" in blockers
    assert "negative-accuracy-drop" in blockers
