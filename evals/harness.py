"""Deterministic evaluation of the QA agents' structured output.

Execution only: artifacts are pushed through the real services (submission checks,
validation, sectioned reads, export gate) in a temporary run store, then scored by the checks
in ``evals.checks``. Three entry points:

* ``evaluate_candidate``: a recorded candidate of a scenario (reference or negative control);
* ``evaluate_stored_run``: a real run in ``output/`` scored against a scenario (universal and
  reference checks; the scenario story is the independent Jira snapshot);
* ``evaluate_stored_run`` without a scenario: any QA Assistant run, universal checks only.

Stored runs are copied to a temporary store first; ``output/`` is never modified.
"""

from __future__ import annotations

import shutil
import tempfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evals import checks as c
from evals.checks import CheckResult, Evidence
from evals.report import EvalResult
from evals.scenario import Candidate, Reference, Scenario
from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Readiness
from qa_assistant.domain.story import JiraStory, StorySearchPage
from qa_assistant.domain.test_case import TestCaseDraft, TestCaseSet
from qa_assistant.domain.validation import ValidationReport
from qa_assistant.errors import ExportBlockedError, InvalidArtifactError, NotFoundError
from qa_assistant.services.export import ExportService
from qa_assistant.services.runs import CASE_PAGE_MAX, INDEX_PAGE_MAX, RunService
from qa_assistant.storage.run_store import RunStore
from qa_assistant.xray.csv_exporter import MappedXrayCsvExporter
from qa_assistant.xray.mapping import XrayCsvMapping

REPO = Path(__file__).resolve().parent.parent
SYNTHETIC_MAPPING = REPO / "tests" / "fixtures" / "xray" / "synthetic_mapping.json"
PAGE_BUDGET = 65_536  # bytes per sectioned MCP read


class _ScenarioJira:
    """Serves the scenario's story the way the real (flagging) Jira client would."""

    def __init__(self, story: JiraStory) -> None:
        self._story = story

    def get_story(self, issue_key: str, *, include_comments: bool = False) -> JiraStory:
        if issue_key != self._story.key:
            raise NotFoundError(f"Issue {issue_key} does not exist.")
        return self._story

    def search_stories(
        self, jql: str, *, max_results: int, next_page_token: str | None = None
    ) -> StorySearchPage:
        return StorySearchPage(issues=[])


def _services(root: Path, story: JiraStory | None) -> tuple[RunStore, RunService, ExportService]:
    store = RunStore(root)
    exporter = MappedXrayCsvExporter(XrayCsvMapping.from_file(SYNTHETIC_MAPPING))
    jira = _ScenarioJira(story) if story else None
    return store, RunService(store, jira), ExportService(store, exporter)


def evaluate_candidate(scenario: Scenario, candidate: Candidate) -> EvalResult:
    with tempfile.TemporaryDirectory(prefix="qa-eval-") as tmp:
        store, runs, export = _services(Path(tmp) / "output", scenario.story)
        metrics: dict[str, Any] = {}
        try:
            submitted = runs.submit_story_analysis(StoryAnalysis.model_validate(candidate.analysis))
        except (ValidationError, InvalidArtifactError) as exc:
            metrics["analysis_rejected"] = str(exc).splitlines()[0][:200]
            checks = [c.check("analysis_accepted", False, str(exc))]
            checks += c.ac_preserved(
                list(scenario.story.acceptance_criteria), candidate.analysis, None, metrics
            )
            return _result(scenario.id, candidate.name, checks, metrics, candidate)
        metrics["analysis_warnings"] = sorted({i.code for i in submitted.issues})
        for revision in filter(None, (candidate.test_cases, candidate.reviewed_test_cases)):
            runs.submit_test_cases(
                submitted.run_id, [TestCaseDraft.model_validate(d) for d in revision]
            )
        checks = _score_run(
            store,
            runs,
            export,
            submitted.run_id,
            scenario=scenario,
            agent_analysis=candidate.analysis,
            metrics=metrics,
        )
        return _result(scenario.id, candidate.name, checks, metrics, candidate)


def evaluate_stored_run(scenario: Scenario | None, output_dir: Path, run_id: str) -> EvalResult:
    """Score a real run (revision 1 = designer, latest = reviewer). Without a scenario only the
    universal checks run, with the run's stored (server-verified) ACs as the requirements."""
    source = RunStore(output_dir)
    manifest = source.get_manifest(run_id)  # validates the id and that the run exists
    with tempfile.TemporaryDirectory(prefix="qa-eval-") as tmp:
        root = Path(tmp) / "output"
        shutil.copytree(output_dir / "runs" / manifest.run_id, root / "runs" / manifest.run_id)
        store, runs, export = _services(root, scenario.story if scenario else None)
        metrics: dict[str, Any] = {"story_key": manifest.story_key}
        checks = _score_run(
            store,
            runs,
            export,
            run_id,
            scenario=scenario,
            agent_analysis=store.load_analysis(run_id).model_dump(mode="json"),
            metrics=metrics,
            always_review=True,
        )
        return _result(scenario.id if scenario else "-", f"run:{run_id}", checks, metrics, None)


def _result(
    scenario_id: str,
    name: str,
    checks: list[CheckResult],
    metrics: dict[str, Any],
    candidate: Candidate | None,
) -> EvalResult:
    return EvalResult(
        scenario=scenario_id,
        candidate=name,
        checks=checks,
        metrics=metrics,
        expected_failed_checks=candidate.expected_failed_checks if candidate else [],
    )


def _score_run(
    store: RunStore,
    runs: RunService,
    export: ExportService,
    run_id: str,
    *,
    scenario: Scenario | None,
    agent_analysis: dict[str, Any],
    metrics: dict[str, Any],
    always_review: bool = False,
) -> list[CheckResult]:
    ref = scenario.reference if scenario else Reference()
    declared = set(scenario.checks) if scenario else set()
    analysis = store.load_analysis(run_id)
    latest = store.get_manifest(run_id).latest_revision
    final = store.load_test_cases(run_id) if latest else None
    report = runs.validate_test_cases(run_id) if latest else None
    story = scenario.story if scenario else None
    evidence = Evidence(analysis=analysis, story=story)
    metrics["findings_by_kind"] = dict(Counter(f.kind.value for f in analysis.findings))
    metrics["risks"] = len(analysis.risks)

    jira_acs = list(story.acceptance_criteria) if story else None
    checks = [
        c.check("analysis_accepted", True),
        *c.ac_preserved(jira_acs, agent_analysis, analysis.acceptance_criteria, metrics),
    ]
    checks.append(c.duplicate_acs_raised(evidence))
    if "expected_findings" in declared:
        checks.append(c.expected_findings(evidence, ref))
    if "injection_ignored" in declared:
        checks.append(c.injection_ignored(evidence, ref, _surfaces(store, run_id, analysis)))

    if final is None or report is None:
        metrics["test_cases"] = 0
        checks.append(c.check("test_cases_submitted", False, "no test cases"))
        return checks

    metrics.update(c.artifact_metrics(evidence, final, report))
    checks += c.test_design(evidence, final, report)
    if "applicable_techniques" in declared:
        checks.append(c.applicable_techniques(final, ref))
    checks += c.readiness(evidence, final, report)
    if "ready_acs" in declared:
        checks.append(c.ready_acs(evidence, final, ref))
    if "expected_blocked" in declared:
        checks.append(c.expected_blocked(evidence, final, ref))
    if "export_readiness" in declared:
        checks.append(
            c.check(
                "export_readiness",
                report.export_ready == ref.export_ready,
                f"export_ready={report.export_ready}",
            )
        )
    checks.append(c.check("validation", report.valid, str(metrics["error_codes"])))
    if final.revision > 1 or always_review:
        first = store.load_test_cases(run_id, 1)
        first_report = runs.validate_test_cases(run_id, 1)
        checks.append(c.reviewer(evidence, first, first_report, final, report, metrics))
    else:
        checks.append(c.skip("reviewer", "no reviewer revision"))
    checks.append(_paged_read(runs, run_id, final, metrics))
    checks.append(_export_gate(export, run_id, final, report))
    return checks


def _surfaces(store: RunStore, run_id: str, analysis: StoryAnalysis) -> list[str]:
    """Where obeyed injected text would show up: ACs, requirements and every revision."""
    latest = store.get_manifest(run_id).latest_revision or 0
    return [
        *(ac.text for ac in analysis.acceptance_criteria),
        *analysis.requirements,
        *(
            store.load_test_cases(run_id, revision).model_dump_json()
            for revision in range(1, latest + 1)
        ),
    ]


# --------------------------------------------------------------------------- system checks


def _pages(runs: RunService, run_id: str) -> Iterator[tuple[str, int, list[str]]]:
    offset: int | None = 0
    while offset is not None:
        index = runs.list_test_cases(run_id, offset=offset, limit=INDEX_PAGE_MAX)
        yield "list_test_cases", len(index.model_dump_json()), [i.id for i in index.items]
        offset = index.next_offset
    offset = 0
    while offset is not None:
        page = runs.get_test_cases(run_id, offset=offset, limit=CASE_PAGE_MAX)
        yield "get_test_cases", len(page.model_dump_json()), [tc.id for tc in page.test_cases]
        offset = page.next_offset


def _paged_read(
    runs: RunService, run_id: str, final: TestCaseSet, metrics: dict[str, Any]
) -> CheckResult:
    """An agent reading only through the sectioned tools sees every case, in bounded pages."""
    sizes = {
        "get_run": len(runs.get_run(run_id).model_dump_json()),
        "get_coverage": len(runs.get_coverage(run_id).model_dump_json()),
    }
    seen: dict[str, list[str]] = {"list_test_cases": [], "get_test_cases": []}
    calls = 0
    for tool, size, ids in _pages(runs, run_id):
        sizes[tool] = max(size, sizes.get(tool, 0))
        seen[tool] += ids
        calls += 1
    expected = [tc.id for tc in final.test_cases]
    complete = all(ids == expected for ids in seen.values())
    metrics.update(max_page_bytes=max(sizes.values()), page_calls=calls)
    over = {tool: size for tool, size in sizes.items() if size > PAGE_BUDGET}
    return c.check("paged_read", complete and not over, f"complete={complete} over_budget={over}")


def _export_gate(
    export: ExportService, run_id: str, final: TestCaseSet, report: ValidationReport
) -> CheckResult:
    """Default export succeeds only when export-ready; a ready_only export never contains a
    clarification_required case."""
    try:
        export.export_xray_csv(run_id)
        exported = True
    except ExportBlockedError:
        exported = False
    if exported != report.export_ready:
        return c.check(
            "export_gate", False, f"exported={exported} export_ready={report.export_ready}"
        )
    if exported or not report.valid or not report.ready_test_case_ids:
        return c.check("export_gate", True)
    try:
        result = export.export_xray_csv(run_id, ready_only=True, overwrite=True)
    except ExportBlockedError:
        return c.check("export_gate", True, "ready_only export blocked (coverage)")
    unclear = {tc.id for tc in final.test_cases if tc.status is Readiness.CLARIFICATION_REQUIRED}
    excluded = set(result.excluded_test_case_ids)
    ok = excluded == unclear and result.test_case_count == len(final.test_cases) - len(unclear)
    return c.check("export_gate", ok, f"excluded={sorted(excluded)}")
