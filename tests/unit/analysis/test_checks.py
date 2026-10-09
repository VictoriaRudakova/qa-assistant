from __future__ import annotations

from qa_assistant.analysis.checks import check_analysis
from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import AcceptanceCriterionSource, Severity
from qa_assistant.domain.story import AcceptanceCriterion, JiraStory
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
    issues = check_analysis(analysis, other)
    assert codes(issues) == ["ANALYSIS_STORY_MISMATCH", "ANALYSIS_DROPPED_AC"]
    assert all(i.severity is Severity.ERROR for i in issues)


def test_acceptance_criterion_not_in_jira_is_an_error(
    analysis: StoryAnalysis, story: JiraStory
) -> None:
    analysis.acceptance_criteria.append(
        AcceptanceCriterion(
            id="AC-5",
            text="Total is recalculated after removal.",
            source=AcceptanceCriterionSource.DESCRIPTION,
        )
    )
    issues = check_analysis(analysis, story)
    assert [(i.code, i.severity) for i in issues] == [("ANALYSIS_NON_JIRA_AC", Severity.ERROR)]
    assert "record the gap as a finding" in issues[0].message


def test_story_without_acceptance_criteria_is_a_warning(analysis: StoryAnalysis) -> None:
    analysis.acceptance_criteria = []
    analysis.risks[0].related_ac_ids = []
    analysis.risks[1].related_ac_ids = []
    analysis.findings[0].related_ac_ids = []
    assert codes(check_analysis(analysis)) == ["ANALYSIS_NO_ACCEPTANCE_CRITERIA"]


def test_duplicate_jira_acs_need_a_finding(analysis: StoryAnalysis, story: JiraStory) -> None:
    duplicated = story.model_copy(deep=True)
    duplicated.acceptance_criteria[3].text = duplicated.acceptance_criteria[0].text.upper()
    analysis.acceptance_criteria[3].text = duplicated.acceptance_criteria[3].text
    issues = check_analysis(analysis, duplicated)
    assert codes(issues) == ["ANALYSIS_DUPLICATE_AC"]
    assert issues[0].severity is Severity.WARNING
    assert "AC-1, AC-4" in issues[0].message

    analysis.findings[0].related_ac_ids = ["AC-1", "AC-4"]
    assert check_analysis(analysis, duplicated) == []


def test_duplicate_acs_are_checked_without_jira(analysis: StoryAnalysis) -> None:
    analysis.acceptance_criteria[1].text = analysis.acceptance_criteria[0].text
    assert codes(check_analysis(analysis)) == ["ANALYSIS_DUPLICATE_AC"]


def test_reworded_acceptance_criterion_is_a_warning(
    analysis: StoryAnalysis, story: JiraStory
) -> None:
    analysis.acceptance_criteria[2].text = "Unknown emails get a generic message."
    analysis.acceptance_criteria[0].text += "  "  # whitespace/punctuation is not rewording
    issues = check_analysis(analysis, story)
    assert codes(issues) == ["ANALYSIS_AC_TEXT_REPLACED"]
    assert "AC-3" in issues[0].message
