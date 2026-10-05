from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from qa_assistant.domain.analysis import Risk, StoryAnalysis, risk_severity
from qa_assistant.domain.enums import Level, Severity
from qa_assistant.domain.story import JiraStory
from qa_assistant.domain.test_case import TestCaseDraft, TestCaseSet
from qa_assistant.domain.validation import ValidationIssue, ValidationReport


def test_story_fixture_is_valid(story: JiraStory) -> None:
    assert story.key == "DEMO-101"
    assert [ac.id for ac in story.acceptance_criteria] == ["AC-1", "AC-2", "AC-3", "AC-4"]


@pytest.mark.parametrize("key", ["demo-1", "DEMO-0", "DEMO", "1DEMO-1", "DEMO-1; DROP"])
def test_issue_key_rejects_malformed(story: JiraStory, key: str) -> None:
    with pytest.raises(ValidationError):
        JiraStory.model_validate({**story.model_dump(), "key": key})


@pytest.mark.parametrize(
    ("likelihood", "impact", "expected"),
    [
        (Level.LOW, Level.LOW, Level.LOW),
        (Level.LOW, Level.MEDIUM, Level.LOW),
        (Level.LOW, Level.HIGH, Level.MEDIUM),
        (Level.MEDIUM, Level.MEDIUM, Level.MEDIUM),
        (Level.MEDIUM, Level.HIGH, Level.HIGH),
        (Level.HIGH, Level.HIGH, Level.HIGH),
    ],
)
def test_risk_severity_matrix(likelihood: Level, impact: Level, expected: Level) -> None:
    assert risk_severity(likelihood, impact) is expected
    assert risk_severity(impact, likelihood) is expected


def test_risk_severity_input_is_ignored_and_recomputed(analysis_data: dict[str, Any]) -> None:
    risk_data = {**analysis_data["risks"][0], "severity": "low"}
    risk = Risk.model_validate(risk_data)
    assert risk.severity is Level.HIGH  # medium x high


def test_analysis_round_trips_through_json(analysis: StoryAnalysis) -> None:
    assert StoryAnalysis.model_validate_json(analysis.model_dump_json()) == analysis


def test_analysis_rejects_unknown_fields(analysis_data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="extra"):
        StoryAnalysis.model_validate({**analysis_data, "csv": "TCID,Summary"})


def test_analysis_rejects_duplicate_ids(analysis_data: dict[str, Any]) -> None:
    data = copy.deepcopy(analysis_data)
    data["risks"][1]["id"] = "R-1"
    with pytest.raises(ValidationError, match="duplicate risk ids: R-1"):
        StoryAnalysis.model_validate(data)


def test_analysis_requires_acceptance_criteria(analysis_data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StoryAnalysis.model_validate({**analysis_data, "acceptance_criteria": []})


def _draft(data: dict[str, Any], **overrides: Any) -> TestCaseDraft:
    return TestCaseDraft.model_validate({**data, **overrides})


def test_draft_requires_steps_and_coverage(drafts_data: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        _draft(drafts_data[0], steps=[])
    with pytest.raises(ValidationError):
        _draft(drafts_data[0], covers=[])


def test_step_requires_expected_result(drafts_data: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        _draft(drafts_data[0], steps=[{"action": "Click submit", "expected_result": ""}])


def test_draft_rejects_duplicate_references(drafts_data: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError, match="covers contains duplicates"):
        _draft(drafts_data[0], covers=["AC-1", "AC-1"])


def test_label_cannot_contain_whitespace(drafts_data: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        _draft(drafts_data[0], labels=["two words"])


def test_test_case_set_rejects_duplicate_ids(test_set: TestCaseSet) -> None:
    cases = [test_set.test_cases[0], test_set.test_cases[0]]
    with pytest.raises(ValidationError, match="duplicate test case ids"):
        TestCaseSet.model_validate({**test_set.model_dump(), "test_cases": cases})


def test_validation_report_valid_and_round_trip() -> None:
    report = ValidationReport(
        issues=[ValidationIssue(code="W", severity=Severity.WARNING, message="m")],
        coverage={"AC-1": ["TC-001"], "AC-2": []},
    )
    assert report.valid
    assert report.uncovered_ac_ids == ["AC-2"]
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report
    error = ValidationIssue(code="E", severity=Severity.ERROR, message="m")
    invalid = ValidationReport(issues=[error])
    assert not invalid.valid
