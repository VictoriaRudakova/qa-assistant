from __future__ import annotations

import pytest

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Severity, Technique
from qa_assistant.domain.test_case import TestCaseDraft, TestCaseSet, TestStep
from qa_assistant.testdesign.coverage import build_coverage
from qa_assistant.testdesign.ids import assign_ids
from qa_assistant.testdesign.rules import validate_test_cases
from tests.support import FIXED_NOW, RUN_ID


def make_set(drafts: list[TestCaseDraft], story_key: str = "DEMO-101") -> TestCaseSet:
    return TestCaseSet(
        run_id=RUN_ID,
        story_key=story_key,
        revision=1,
        created_at=FIXED_NOW,
        test_cases=assign_ids(drafts),
    )


def codes(test_set: TestCaseSet, analysis: StoryAnalysis) -> list[str]:
    return [i.code for i in validate_test_cases(test_set, analysis).issues]


def test_assign_ids_is_sequential_and_zero_padded(drafts: list[TestCaseDraft]) -> None:
    cases = assign_ids(drafts)
    assert [c.id for c in cases] == ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"]


def test_fixture_set_is_valid_with_full_coverage(
    test_set: TestCaseSet, analysis: StoryAnalysis
) -> None:
    report = validate_test_cases(test_set, analysis)
    assert report.issues == []
    assert report.valid
    assert report.coverage == {
        "AC-1": ["TC-001"],
        "AC-2": ["TC-002", "TC-003"],
        "AC-3": ["TC-004"],
        "AC-4": ["TC-005"],
    }


def test_uncovered_ac_is_an_error(drafts: list[TestCaseDraft], analysis: StoryAnalysis) -> None:
    report = validate_test_cases(make_set(drafts[:4]), analysis)
    assert not report.valid
    assert [i.code for i in report.errors] == ["AC_NOT_COVERED"]
    assert report.uncovered_ac_ids == ["AC-4"]


def test_unknown_references_are_errors(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[0].covers = ["AC-1", "AC-99"]
    drafts[0].risk_ids = ["R-42"]
    report = validate_test_cases(make_set(drafts), analysis)
    assert {(i.code, i.test_case_id) for i in report.errors} == {
        ("TC_UNKNOWN_AC", "TC-001"),
        ("TC_UNKNOWN_RISK", "TC-001"),
    }


def test_story_mismatch(drafts: list[TestCaseDraft], analysis: StoryAnalysis) -> None:
    assert "TC_STORY_MISMATCH" in codes(make_set(drafts, "DEMO-999"), analysis)


def test_duplicate_titles_and_steps_are_warnings(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[1].title = drafts[0].title.upper() + "!"
    drafts[1].steps = [drafts[1].steps[0], drafts[1].steps[0]]
    report = validate_test_cases(make_set(drafts), analysis)
    assert report.valid
    assert sorted(i.code for i in report.warnings) == [
        "TC_DUPLICATE_STEP",
        "TC_DUPLICATE_TITLE",
        "TC_DUPLICATE_TITLE",
    ]


@pytest.mark.parametrize("expected", ["Works as expected.", "as expected", "  success "])
def test_vague_expected_result_is_a_warning(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis, expected: str
) -> None:
    drafts[0].steps = [TestStep(action="Open the page", expected_result=expected)]
    report = validate_test_cases(make_set(drafts), analysis)
    assert [(i.code, i.severity) for i in report.issues] == [
        ("TC_VAGUE_EXPECTED_RESULT", Severity.WARNING)
    ]


def test_high_risk_without_test_is_a_warning(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[3].risk_ids = []  # R-1 is medium x high -> high severity
    assert codes(make_set(drafts), analysis) == ["RISK_HIGH_UNTESTED"]


def test_missing_negative_tests_is_a_warning(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[3].technique = Technique.POSITIVE
    assert codes(make_set(drafts), analysis) == ["SET_NO_NEGATIVE_TESTS"]


def test_coverage_orders_ac_ids_numerically(test_set: TestCaseSet) -> None:
    coverage = build_coverage({"AC-10", "AC-2", "AC-1"}, test_set.test_cases)
    assert list(coverage) == ["AC-1", "AC-2", "AC-10"]
