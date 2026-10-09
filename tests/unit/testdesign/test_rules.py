from __future__ import annotations

import pytest

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Readiness, Severity, Technique
from qa_assistant.domain.test_case import TestCaseDraft, TestCaseSet, TestStep
from qa_assistant.testdesign.coverage import (
    build_coverage,
    build_coverage_report,
    build_finding_coverage,
)
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
    assert report.finding_coverage == {"F-1": [], "F-2": []}
    assert report.ready_test_case_ids == ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"]
    assert report.clarification_required_test_case_ids == []
    assert report.export_ready


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


def test_unknown_finding_references_are_errors(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[0].finding_ids = ["F-9"]
    drafts[0].status = Readiness.CLARIFICATION_REQUIRED
    drafts[0].open_question_ids = ["F-8"]
    report = validate_test_cases(make_set(drafts), analysis)
    assert [(i.code, i.field) for i in report.errors] == [
        ("TC_UNKNOWN_FINDING", "finding_ids"),
        ("TC_UNKNOWN_FINDING", "open_question_ids"),
    ]


def test_case_must_trace_to_something(drafts: list[TestCaseDraft], analysis: StoryAnalysis) -> None:
    drafts.append(drafts[0].model_copy(update={"title": "Untraced case", "covers": []}))
    report = validate_test_cases(make_set(drafts), analysis)
    assert [(i.code, i.test_case_id) for i in report.errors] == [("TC_NO_TRACEABILITY", "TC-006")]


def test_gap_test_traces_to_finding_without_an_acceptance_criterion(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts.append(
        drafts[2].model_copy(
            update={
                "title": "Used reset link cannot be reused",
                "covers": [],
                "finding_ids": ["F-1"],
            }
        )
    )
    report = validate_test_cases(make_set(drafts), analysis)
    assert report.export_ready
    assert report.finding_coverage == {"F-1": ["TC-006"], "F-2": []}
    assert "TC-006" not in {tc for tcs in report.coverage.values() for tc in tcs}


def test_clarification_required_case_is_identified_and_blocks_export(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[1].status = Readiness.CLARIFICATION_REQUIRED
    drafts[1].open_question_ids = ["F-2"]
    report = validate_test_cases(make_set(drafts), analysis)
    assert report.valid
    assert not report.export_ready
    assert report.clarification_required_test_case_ids == ["TC-002"]
    assert "TC-002" not in report.ready_test_case_ids
    assert [(i.code, i.test_case_id) for i in report.warnings] == [
        ("TC_CLARIFICATION_REQUIRED", "TC-002")
    ]
    assert report.finding_coverage["F-2"] == ["TC-002"]


def test_clarification_without_question_is_an_error(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[0].status = Readiness.CLARIFICATION_REQUIRED
    assert [i.code for i in validate_test_cases(make_set(drafts), analysis).errors] == [
        "TC_CLARIFICATION_WITHOUT_QUESTION"
    ]


def test_ready_case_with_open_question_is_an_error(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[0].open_question_ids = ["F-2"]
    assert [i.code for i in validate_test_cases(make_set(drafts), analysis).errors] == [
        "TC_READY_WITH_OPEN_QUESTION"
    ]


@pytest.mark.parametrize(
    "expected",
    [
        "Line is either removed or the value is rejected.",
        "Unit price is 12.50 or 15.00 (record which).",
        "Quantity follows the rule agreed with the PO.",
        "Confirmation is shown (exact feedback pending F-8).",
        "Message text TBD.",
        "Behaviour to be confirmed by product.",
        "Outcome depending on the stock policy.",
    ],
)
def test_undecided_expected_result_in_ready_case_is_an_error(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis, expected: str
) -> None:
    drafts[0].steps = [TestStep(action="Open the page", expected_result=expected)]
    report = validate_test_cases(make_set(drafts), analysis)
    assert [(i.code, i.test_case_id) for i in report.errors] == [
        ("TC_UNRESOLVED_EXPECTED_RESULT", "TC-001")
    ]


@pytest.mark.parametrize(
    "expected", ["Order status shows Pending.", "Neither link is shown.", "Shows 2 or more rows."]
)
def test_definite_expected_results_are_not_flagged(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis, expected: str
) -> None:
    drafts[0].steps = [TestStep(action="Open the page", expected_result=expected)]
    assert validate_test_cases(make_set(drafts), analysis).valid


def test_undecided_wording_is_allowed_when_clarification_is_required(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[0].steps = [TestStep(action="Open the page", expected_result="Either A or B.")]
    drafts[0].status = Readiness.CLARIFICATION_REQUIRED
    drafts[0].open_question_ids = ["F-2"]
    drafts[0].labels = ["open-question-F-2"]
    assert validate_test_cases(make_set(drafts), analysis).valid


def test_open_question_label_on_ready_case_is_an_error(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[0].labels = ["cart", "open-question-F-2"]
    report = validate_test_cases(make_set(drafts), analysis)
    assert [(i.code, i.field) for i in report.errors] == [
        ("TC_UNRESOLVED_EXPECTED_RESULT", "labels")
    ]


def test_ac_covered_only_by_clarification_cases_is_a_warning(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    drafts[0].status = Readiness.CLARIFICATION_REQUIRED
    drafts[0].open_question_ids = ["F-2"]
    report = validate_test_cases(make_set(drafts), analysis)
    assert "AC_ONLY_CLARIFICATION_COVERAGE" in [i.code for i in report.warnings]
    assert report.uncovered_ac_ids == []


def test_finding_coverage_orders_ids_numerically(test_set: TestCaseSet) -> None:
    assert list(build_finding_coverage({"F-10", "F-2"}, test_set.test_cases)) == ["F-2", "F-10"]


def test_ready_case_tracing_only_to_a_gap_blocks_export(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    gap_only = drafts[0].model_copy(
        update={"title": "Reset link can be used twice", "covers": [], "finding_ids": ["F-1"]}
    )
    with_risk = gap_only.model_copy(update={"title": "Reset link reuse", "risk_ids": ["R-1"]})
    report = validate_test_cases(make_set([*drafts, gap_only, with_risk]), analysis)
    flagged = [(i.code, i.test_case_id) for i in report.issues if i.code == "TC_READY_GAP_ONLY"]
    assert flagged == [("TC_READY_GAP_ONLY", "TC-006")]
    assert [i.code for i in report.errors] == ["TC_READY_GAP_ONLY"]
    assert not report.valid
    assert not report.export_ready

    unclear = gap_only.model_copy(
        update={"status": Readiness.CLARIFICATION_REQUIRED, "open_question_ids": ["F-1"]}
    )
    assert "TC_READY_GAP_ONLY" not in codes(make_set([*drafts, unclear]), analysis)


def test_coverage_report_separates_authoritative_and_inferred(
    drafts: list[TestCaseDraft], analysis: StoryAnalysis
) -> None:
    unclear = drafts[4].model_copy(
        update={
            "status": Readiness.CLARIFICATION_REQUIRED,
            "open_question_ids": ["F-2"],
            "risk_ids": ["R-2"],
        }
    )
    report = build_coverage_report(make_set([*drafts[:4], unclear]), analysis)
    assert report.acceptance_criteria["AC-4"] == ["TC-005"]
    assert report.acceptance_criteria_ready["AC-4"] == []
    assert report.uncovered_ac_ids == []
    assert report.ac_ids_without_ready_test == ["AC-4"]
    assert report.findings["F-2"] == ["TC-005"]
    assert report.risks["R-2"] == ["TC-003", "TC-005"]
    assert report.clarification_required_test_case_ids == ["TC-005"]
    assert "AC-4" not in report.findings
    assert "F-2" not in report.acceptance_criteria
