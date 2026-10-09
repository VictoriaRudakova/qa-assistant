"""Results returned by application services (and therefore by MCP tools)."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import Field

from qa_assistant.domain.base import DomainModel, IssueKey, RunId, TestCaseId
from qa_assistant.domain.enums import Priority, Readiness, Technique
from qa_assistant.domain.test_case import TestCase
from qa_assistant.domain.validation import ValidationIssue, ValidationReport


class RunManifest(DomainModel):
    run_id: RunId
    story_key: IssueKey
    created_at: datetime
    latest_revision: int | None = None


class RunOverview(DomainModel):
    """Small, bounded summary of a run. Sections are read with the dedicated tools
    (get_story_analysis, list_test_cases, get_test_cases, validate_test_cases) so that no
    single response grows with the number of test cases."""

    manifest: RunManifest
    acceptance_criterion_ids: list[str] = Field(description="Authoritative Jira ACs")
    finding_ids: list[str]
    risk_ids: list[str]
    revision: int | None = Field(description="Requested (default: latest) test-case revision")
    test_case_count: int = 0
    ready_count: int = 0
    clarification_required_count: int = 0


class TestCaseSummary(DomainModel):
    """One line of the test-case index: traceability and status without steps."""

    __test__: ClassVar[bool] = False

    id: TestCaseId
    title: str
    status: Readiness
    priority: Priority
    technique: Technique
    covers: list[str]
    risk_ids: list[str]
    finding_ids: list[str]
    open_question_ids: list[str]
    step_count: int


class TestCaseIndexPage(DomainModel):
    __test__: ClassVar[bool] = False

    run_id: RunId
    revision: int
    total: int = Field(description="Number of test cases in the revision")
    offset: int
    next_offset: int | None = Field(description="Pass as offset for the next page; null at end")
    items: list[TestCaseSummary]


class TestCasePage(DomainModel):
    __test__: ClassVar[bool] = False

    run_id: RunId
    revision: int
    total: int = Field(description="Number of test cases in the revision")
    offset: int
    next_offset: int | None = Field(description="Pass as offset for the next page; null at end")
    test_cases: list[TestCase]


class SubmitAnalysisResult(DomainModel):
    run_id: RunId
    story_key: IssueKey
    issues: list[ValidationIssue] = Field(
        default_factory=list, description="Non-blocking warnings about the analysis"
    )


class SubmitTestCasesResult(DomainModel):
    run_id: RunId
    revision: int
    test_case_count: int
    report: ValidationReport


class ExportResult(DomainModel):
    run_id: RunId
    revision: int
    path: str
    mapping_name: str
    rows: int
    test_case_count: int
    sha256: str
    excluded_test_case_ids: list[str] = Field(
        default_factory=list,
        description="clarification_required cases left out of the file (ready_only export)",
    )
    warnings: list[str] = Field(default_factory=list)
