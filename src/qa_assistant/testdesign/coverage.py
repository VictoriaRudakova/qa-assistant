from __future__ import annotations

from collections.abc import Iterable, Sequence

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Readiness
from qa_assistant.domain.test_case import TestCase, TestCaseSet
from qa_assistant.domain.validation import CoverageReport


def build_coverage(ac_ids: Iterable[str], test_cases: Sequence[TestCase]) -> dict[str, list[str]]:
    """Map each acceptance criterion id to the ids of the test cases covering it."""
    coverage: dict[str, list[str]] = {ac_id: [] for ac_id in sorted(ac_ids, key=_id_sort_key)}
    for tc in test_cases:
        for ac_id in tc.covers:
            if ac_id in coverage:
                coverage[ac_id].append(tc.id)
    return coverage


def build_finding_coverage(
    finding_ids: Iterable[str], test_cases: Sequence[TestCase]
) -> dict[str, list[str]]:
    """Map each finding id to the test cases exploring it or waiting on its answer.

    Findings are requirement gaps and questions, not acceptance criteria, so this is reported
    separately from :func:`build_coverage` and never satisfies AC coverage.
    """
    coverage: dict[str, list[str]] = {f: [] for f in sorted(finding_ids, key=_id_sort_key)}
    for tc in test_cases:
        for finding_id in dict.fromkeys([*tc.finding_ids, *tc.open_question_ids]):
            if finding_id in coverage:
                coverage[finding_id].append(tc.id)
    return coverage


def build_risk_coverage(
    risk_ids: Iterable[str], test_cases: Sequence[TestCase]
) -> dict[str, list[str]]:
    """Map each risk id to the test cases mitigating it (inferred, not AC coverage)."""
    coverage: dict[str, list[str]] = {r: [] for r in sorted(risk_ids, key=_id_sort_key)}
    for tc in test_cases:
        for risk_id in tc.risk_ids:
            if risk_id in coverage:
                coverage[risk_id].append(tc.id)
    return coverage


def build_coverage_report(test_set: TestCaseSet, analysis: StoryAnalysis) -> CoverageReport:
    cases = test_set.test_cases
    ready = [tc for tc in cases if tc.status is Readiness.READY]
    return CoverageReport(
        run_id=test_set.run_id,
        revision=test_set.revision,
        acceptance_criteria=build_coverage(analysis.ac_ids, cases),
        acceptance_criteria_ready=build_coverage(analysis.ac_ids, ready),
        findings=build_finding_coverage(analysis.finding_ids, cases),
        risks=build_risk_coverage(analysis.risk_ids, cases),
        ready_test_case_ids=[tc.id for tc in ready],
        clarification_required_test_case_ids=[
            tc.id for tc in cases if tc.status is Readiness.CLARIFICATION_REQUIRED
        ],
    )


def _id_sort_key(ac_id: str) -> tuple[int, str]:
    _, _, number = ac_id.partition("-")
    return (int(number), ac_id) if number.isdigit() else (0, ac_id)
