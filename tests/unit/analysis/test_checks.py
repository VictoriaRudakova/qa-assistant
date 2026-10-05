from __future__ import annotations

from qa_assistant.analysis.checks import check_analysis
from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Severity
from qa_assistant.domain.story import JiraStory
from qa_assistant.domain.validation import ValidationIssue


def codes(issues: list[ValidationIssue]) -> list[str]:
    return [i.code for i in issues]


def test_fixture_analysis_is_clean(analysis: StoryAnalysis, story: JiraStory) -> None:
    assert check_analysis(analysis, story) == []


def test_unknown_ac_references(analysis: StoryAnalysis) -> None:
    analysis.risks[0].related_ac_ids = ["AC-9"]
    analysis.findings[0].related_ac_ids = ["AC-8"]
    issues = check_analysis(analysis)
    assert codes(issues) == ["ANALYSIS_UNKNOWN_AC", "ANALYSIS_UNKNOWN_AC"]
    assert all(i.severity is Severity.ERROR for i in issues)


def test_no_risks_is_a_warning(analysis: StoryAnalysis) -> None:
    analysis.risks = []
    assert codes(check_analysis(analysis)) == ["ANALYSIS_NO_RISKS"]


def test_story_mismatch_and_dropped_ac(analysis: StoryAnalysis, story: JiraStory) -> None:
    analysis.acceptance_criteria = analysis.acceptance_criteria[:3]
    other = story.model_copy(update={"key": "DEMO-102"})
    assert codes(check_analysis(analysis, other)) == [
        "ANALYSIS_STORY_MISMATCH",
        "ANALYSIS_DROPPED_AC",
    ]
