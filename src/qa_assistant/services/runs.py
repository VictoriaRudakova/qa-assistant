"""Accepts structured QA artifacts from the LLM, validates them and persists them."""

from __future__ import annotations

from collections.abc import Sequence

from qa_assistant.analysis.checks import check_analysis
from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Readiness, Severity
from qa_assistant.domain.results import (
    RunManifest,
    RunOverview,
    SubmitAnalysisResult,
    SubmitTestCasesResult,
    TestCaseIndexPage,
    TestCasePage,
    TestCaseSummary,
)
from qa_assistant.domain.story import JiraStory
from qa_assistant.domain.test_case import TestCase, TestCaseDraft, TestCaseSet
from qa_assistant.domain.validation import CoverageReport, ValidationIssue, ValidationReport
from qa_assistant.errors import InvalidArtifactError, NotConfiguredError, NotFoundError
from qa_assistant.jira.ports import JiraClient
from qa_assistant.storage.run_store import RunStore
from qa_assistant.testdesign.coverage import build_coverage_report
from qa_assistant.testdesign.ids import assign_ids
from qa_assistant.testdesign.rules import validate_test_cases

INDEX_PAGE_MAX = 100
CASE_PAGE_MAX = 25


class RunService:
    def __init__(self, store: RunStore, jira: JiraClient | None = None) -> None:
        self._store = store
        self._jira = jira

    def submit_story_analysis(self, analysis: StoryAnalysis) -> SubmitAnalysisResult:
        """Validate an analysis and start a new run with it. Errors reject the submission.

        When Jira is available the story is re-fetched: the analysis must carry exactly its
        acceptance criteria, and the stored criteria are Jira's own wording.
        """
        story, unverified = self._fetch_story(analysis.story_key)
        issues = check_analysis(analysis, story)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        if errors:
            raise InvalidArtifactError("; ".join(f"{i.code}: {i.message}" for i in errors))
        if story is not None:
            analysis = analysis.model_copy(
                update={"acceptance_criteria": list(story.acceptance_criteria)}
            )
        if unverified is not None:
            issues.append(unverified)
        manifest = self._store.create_run(analysis.story_key)
        self._store.save_analysis(manifest.run_id, analysis)
        return SubmitAnalysisResult(
            run_id=manifest.run_id, story_key=manifest.story_key, issues=issues
        )

    def _fetch_story(self, story_key: str) -> tuple[JiraStory | None, ValidationIssue | None]:
        if self._jira is None:
            return None, None
        try:
            return self._jira.get_story(story_key), None
        except NotConfiguredError:
            return None, ValidationIssue(
                code="ANALYSIS_ACS_UNVERIFIED",
                severity=Severity.WARNING,
                message="Jira is not configured, so the acceptance criteria could not be "
                "checked against Jira. Confirm they match the story exactly.",
                field="acceptance_criteria",
            )

    def submit_test_cases(
        self, run_id: str, drafts: Sequence[TestCaseDraft]
    ) -> SubmitTestCasesResult:
        """Store a new revision of test cases and return its validation report.

        Invalid test cases are still stored (so the reviewer can fix them); export is what
        refuses invalid revisions.
        """
        analysis = self._store.load_analysis(run_id)
        test_set = TestCaseSet(
            run_id=run_id,
            story_key=analysis.story_key,
            revision=self._store.next_revision(run_id),
            created_at=self._store.now(),
            test_cases=assign_ids(drafts),
        )
        report = validate_test_cases(test_set, analysis)
        self._store.save_test_cases(test_set)
        return SubmitTestCasesResult(
            run_id=run_id,
            revision=test_set.revision,
            test_case_count=len(test_set.test_cases),
            report=report,
        )

    def validate_test_cases(self, run_id: str, revision: int | None = None) -> ValidationReport:
        """Validate a stored revision (default: latest)."""
        test_set = self._store.load_test_cases(run_id, revision)
        return validate_test_cases(test_set, self._store.load_analysis(run_id))

    def get_coverage(self, run_id: str, revision: int | None = None) -> CoverageReport:
        """AC, finding and risk coverage of a stored revision (default: latest)."""
        test_set = self._store.load_test_cases(run_id, revision)
        return build_coverage_report(test_set, self._store.load_analysis(run_id))

    def get_run(self, run_id: str, revision: int | None = None) -> RunOverview:
        """Bounded overview: manifest, analysis ids and test-case counts by readiness."""
        manifest = self._store.get_manifest(run_id)
        analysis = self._store.load_analysis(run_id)
        cases: list[TestCase] = []
        resolved: int | None = None
        if manifest.latest_revision is not None or revision is not None:
            test_set = self._store.load_test_cases(run_id, revision)
            cases, resolved = test_set.test_cases, test_set.revision
        ready = sum(tc.status is Readiness.READY for tc in cases)
        return RunOverview(
            manifest=manifest,
            acceptance_criterion_ids=[ac.id for ac in analysis.acceptance_criteria],
            finding_ids=[f.id for f in analysis.findings],
            risk_ids=[r.id for r in analysis.risks],
            revision=resolved,
            test_case_count=len(cases),
            ready_count=ready,
            clarification_required_count=len(cases) - ready,
        )

    def get_story_analysis(self, run_id: str) -> StoryAnalysis:
        return self._store.load_analysis(run_id)

    def list_test_cases(
        self, run_id: str, revision: int | None = None, offset: int = 0, limit: int = 50
    ) -> TestCaseIndexPage:
        """One page of the test-case index (no steps)."""
        test_set = self._store.load_test_cases(run_id, revision)
        page, next_offset = _page(test_set.test_cases, offset, min(limit, INDEX_PAGE_MAX))
        return TestCaseIndexPage(
            run_id=run_id,
            revision=test_set.revision,
            total=len(test_set.test_cases),
            offset=offset,
            next_offset=next_offset,
            items=[_summary(tc) for tc in page],
        )

    def get_test_cases(
        self,
        run_id: str,
        revision: int | None = None,
        *,
        ids: Sequence[str] | None = None,
        offset: int = 0,
        limit: int = 10,
    ) -> TestCasePage:
        """Full test cases, by id or one page at a time."""
        test_set = self._store.load_test_cases(run_id, revision)
        if ids:
            if len(ids) > CASE_PAGE_MAX:
                raise InvalidArtifactError(f"Request at most {CASE_PAGE_MAX} ids per call.")
            by_id = {tc.id: tc for tc in test_set.test_cases}
            missing = [i for i in ids if i not in by_id]
            if missing:
                raise NotFoundError(
                    f"Revision {test_set.revision} has no test case(s) {', '.join(missing)}."
                )
            page, offset, next_offset = [by_id[i] for i in ids], 0, None
        else:
            page, next_offset = _page(test_set.test_cases, offset, min(limit, CASE_PAGE_MAX))
        return TestCasePage(
            run_id=run_id,
            revision=test_set.revision,
            total=len(test_set.test_cases),
            offset=offset,
            next_offset=next_offset,
            test_cases=page,
        )

    def list_runs(self, story_key: str | None = None, limit: int = 20) -> list[RunManifest]:
        """Runs, newest first, optionally for one story."""
        return self._store.list_runs(story_key)[:limit]


def _page(cases: list[TestCase], offset: int, limit: int) -> tuple[list[TestCase], int | None]:
    end = offset + limit
    return cases[offset:end], end if end < len(cases) else None


def _summary(tc: TestCase) -> TestCaseSummary:
    return TestCaseSummary(
        id=tc.id,
        title=tc.title,
        status=tc.status,
        priority=tc.priority,
        technique=tc.technique,
        covers=tc.covers,
        risk_ids=tc.risk_ids,
        finding_ids=tc.finding_ids,
        open_question_ids=tc.open_question_ids,
        step_count=len(tc.steps),
    )
