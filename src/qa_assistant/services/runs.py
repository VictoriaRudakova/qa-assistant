"""Accepts structured QA artifacts from the LLM, validates them and persists them."""

from __future__ import annotations

from collections.abc import Sequence

from qa_assistant.analysis.checks import check_analysis
from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Severity
from qa_assistant.domain.results import (
    RunDetails,
    RunManifest,
    SubmitAnalysisResult,
    SubmitTestCasesResult,
)
from qa_assistant.domain.test_case import TestCaseDraft, TestCaseSet
from qa_assistant.domain.validation import ValidationReport
from qa_assistant.errors import InvalidArtifactError
from qa_assistant.storage.run_store import RunStore
from qa_assistant.testdesign.ids import assign_ids
from qa_assistant.testdesign.rules import validate_test_cases


class RunService:
    def __init__(self, store: RunStore) -> None:
        self._store = store

    def submit_story_analysis(self, analysis: StoryAnalysis) -> SubmitAnalysisResult:
        """Validate an analysis and start a new run with it. Errors reject the submission."""
        issues = check_analysis(analysis)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        if errors:
            raise InvalidArtifactError("; ".join(i.message for i in errors))
        manifest = self._store.create_run(analysis.story_key)
        self._store.save_analysis(manifest.run_id, analysis)
        return SubmitAnalysisResult(
            run_id=manifest.run_id, story_key=manifest.story_key, issues=issues
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

    def get_run(self, run_id: str, revision: int | None = None) -> RunDetails:
        """Manifest, analysis and a test-case revision (default: latest, if any)."""
        manifest = self._store.get_manifest(run_id)
        test_cases = (
            self._store.load_test_cases(run_id, revision)
            if manifest.latest_revision is not None or revision is not None
            else None
        )
        return RunDetails(
            manifest=manifest, analysis=self._store.load_analysis(run_id), test_cases=test_cases
        )

    def list_runs(self, story_key: str | None = None, limit: int = 20) -> list[RunManifest]:
        """Runs, newest first, optionally for one story."""
        return self._store.list_runs(story_key)[:limit]
