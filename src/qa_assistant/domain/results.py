"""Results returned by application services (and therefore by MCP tools)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.base import DomainModel, IssueKey, RunId
from qa_assistant.domain.test_case import TestCaseSet
from qa_assistant.domain.validation import ValidationIssue, ValidationReport


class RunManifest(DomainModel):
    run_id: RunId
    story_key: IssueKey
    created_at: datetime
    latest_revision: int | None = None


class RunDetails(DomainModel):
    """Everything an agent needs to continue a run, without knowing the storage layout."""

    manifest: RunManifest
    analysis: StoryAnalysis
    test_cases: TestCaseSet | None = Field(
        default=None, description="Requested (default: latest) revision; null if none submitted"
    )


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
    warnings: list[str] = Field(default_factory=list)
