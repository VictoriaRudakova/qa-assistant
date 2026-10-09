"""Deterministic validation rules for test cases.

Errors block export; warnings are surfaced to the reviewer agent and the user.
Rule codes are a stable contract (skills and agents refer to them) — do not rename.
"""

from __future__ import annotations

import re
from collections import defaultdict

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import NEGATIVE_TECHNIQUES, Level, Readiness, Severity
from qa_assistant.domain.test_case import TestCase, TestCaseSet
from qa_assistant.domain.validation import ValidationIssue, ValidationReport
from qa_assistant.testdesign.coverage import (
    build_coverage,
    build_finding_coverage,
    build_risk_coverage,
)

VAGUE_EXPECTED_RESULTS = frozenset(
    {
        "as expected",
        "it works",
        "ok",
        "passes",
        "success",
        "successful",
        "works",
        "works as expected",
        "works correctly",
        "no errors",
        "correct result",
    }
)


# Phrases that mean the expected behaviour is not actually known. A "ready" case containing
# one must be rewritten with a definite expectation, or marked clarification_required.
UNDECIDED_EXPECTED_RESULT = re.compile(
    r"\b(?:either|tbd|to be (?:confirmed|decided|defined|clarified)|open question"
    r"|pending (?:f\d+|po|clarification|confirmation|decision)"
    r"|record (?:which|what|whether|the observed)|depending on|per (?:the )?po"
    r"|po decision|agreed with the po|unless the po)\b"
)
OPEN_QUESTION_LABEL_PREFIX = "open-question"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.casefold())).strip()


def _issue(
    code: str,
    severity: Severity,
    message: str,
    test_case_id: str | None = None,
    field: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code, severity=severity, message=message, test_case_id=test_case_id, field=field
    )


def _check_references(tc: TestCase, analysis: StoryAnalysis) -> list[ValidationIssue]:
    issues = [
        _issue(
            "TC_UNKNOWN_AC",
            Severity.ERROR,
            f"Covers unknown acceptance criterion {ac_id}.",
            tc.id,
            "covers",
        )
        for ac_id in tc.covers
        if ac_id not in analysis.ac_ids
    ]
    issues += [
        _issue(
            "TC_UNKNOWN_RISK", Severity.ERROR, f"References unknown risk {r}.", tc.id, "risk_ids"
        )
        for r in tc.risk_ids
        if r not in analysis.risk_ids
    ]
    issues += [
        _issue(
            "TC_UNKNOWN_FINDING", Severity.ERROR, f"References unknown finding {f}.", tc.id, field
        )
        for field in ("finding_ids", "open_question_ids")
        for f in getattr(tc, field)
        if f not in analysis.finding_ids
    ]
    if not (tc.covers or tc.risk_ids or tc.finding_ids):
        issues.append(
            _issue(
                "TC_NO_TRACEABILITY",
                Severity.ERROR,
                "Traces to nothing: set covers (Jira ACs), risk_ids or finding_ids.",
                tc.id,
                "covers",
            )
        )
    return issues


def _check_readiness(tc: TestCase) -> list[ValidationIssue]:
    if tc.status is Readiness.CLARIFICATION_REQUIRED:
        if not tc.open_question_ids:
            return [
                _issue(
                    "TC_CLARIFICATION_WITHOUT_QUESTION",
                    Severity.ERROR,
                    "Needs clarification but names no open question in open_question_ids.",
                    tc.id,
                    "open_question_ids",
                )
            ]
        return [
            _issue(
                "TC_CLARIFICATION_REQUIRED",
                Severity.WARNING,
                "Expected behaviour depends on unanswered "
                f"{', '.join(tc.open_question_ids)}; excluded from export until resolved.",
                tc.id,
                "status",
            )
        ]

    issues: list[ValidationIssue] = []
    if tc.finding_ids and not (tc.covers or tc.risk_ids):
        issues.append(
            _issue(
                "TC_READY_GAP_ONLY",
                Severity.ERROR,
                f"Marked ready but traces only to finding(s) {', '.join(tc.finding_ids)}: its "
                "expected results are not backed by a Jira acceptance criterion or a risk. "
                "Mark it clarification_required (with open_question_ids), or trace it to the "
                "Jira acceptance criterion (covers) or risk (risk_ids) that specifies it.",
                tc.id,
                "status",
            )
        )
    if tc.open_question_ids:
        issues.append(
            _issue(
                "TC_READY_WITH_OPEN_QUESTION",
                Severity.ERROR,
                f"Marked ready but depends on open question(s) {', '.join(tc.open_question_ids)}; "
                "set status to clarification_required or remove them.",
                tc.id,
                "status",
            )
        )
    for number, step in enumerate(tc.steps, start=1):
        match = UNDECIDED_EXPECTED_RESULT.search(_normalize(step.expected_result))
        if match:
            issues.append(
                _issue(
                    "TC_UNRESOLVED_EXPECTED_RESULT",
                    Severity.ERROR,
                    f"Step {number} expected result is undecided ({match.group(0)!r}); state one "
                    "definite outcome or mark the case clarification_required.",
                    tc.id,
                    "steps",
                )
            )
    issues += [
        _issue(
            "TC_UNRESOLVED_EXPECTED_RESULT",
            Severity.ERROR,
            f"Marked ready but labelled {label!r}; mark it clarification_required instead.",
            tc.id,
            "labels",
        )
        for label in tc.labels
        if label.casefold().startswith(OPEN_QUESTION_LABEL_PREFIX)
    ]
    return issues


def _check_steps(tc: TestCase) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[tuple[str, str]] = set()
    for number, step in enumerate(tc.steps, start=1):
        key = (_normalize(step.action), _normalize(step.expected_result))
        if key in seen:
            issues.append(
                _issue(
                    "TC_DUPLICATE_STEP",
                    Severity.WARNING,
                    f"Step {number} duplicates an earlier step.",
                    tc.id,
                    "steps",
                )
            )
        seen.add(key)
        if _normalize(step.expected_result) in VAGUE_EXPECTED_RESULTS:
            issues.append(
                _issue(
                    "TC_VAGUE_EXPECTED_RESULT",
                    Severity.WARNING,
                    f"Step {number} expected result is not verifiable: {step.expected_result!r}.",
                    tc.id,
                    "steps",
                )
            )
    return issues


def _check_duplicate_titles(test_cases: list[TestCase]) -> list[ValidationIssue]:
    by_title: dict[str, list[str]] = defaultdict(list)
    for tc in test_cases:
        by_title[_normalize(tc.title)].append(tc.id)
    return [
        _issue(
            "TC_DUPLICATE_TITLE",
            Severity.WARNING,
            f"Same title as {', '.join(ids[:i] + ids[i + 1 :])}.",
            tc_id,
            "title",
        )
        for ids in by_title.values()
        if len(ids) > 1
        for i, tc_id in enumerate(ids)
    ]


def validate_test_cases(test_set: TestCaseSet, analysis: StoryAnalysis) -> ValidationReport:
    """Run every rule against one revision of test cases."""
    issues: list[ValidationIssue] = []
    if test_set.story_key != analysis.story_key:
        issues.append(
            _issue(
                "TC_STORY_MISMATCH",
                Severity.ERROR,
                f"Test cases are for {test_set.story_key}, analysis is for {analysis.story_key}.",
            )
        )
    for tc in test_set.test_cases:
        issues += _check_references(tc, analysis)
        issues += _check_readiness(tc)
        issues += _check_steps(tc)
    issues += _check_duplicate_titles(test_set.test_cases)

    coverage = build_coverage(analysis.ac_ids, test_set.test_cases)
    ready = [tc.id for tc in test_set.test_cases if tc.status is Readiness.READY]
    issues += [
        _issue(
            "AC_NOT_COVERED",
            Severity.ERROR,
            f"Acceptance criterion {ac_id} is not covered by any test case.",
        )
        for ac_id, tcs in coverage.items()
        if not tcs
    ]
    issues += [
        _issue(
            "AC_ONLY_CLARIFICATION_COVERAGE",
            Severity.WARNING,
            f"Acceptance criterion {ac_id} is covered only by cases that need clarification "
            f"({', '.join(tcs)}); no exportable test verifies it yet.",
        )
        for ac_id, tcs in coverage.items()
        if tcs and not set(tcs) & set(ready)
    ]

    mitigated = {r for tc in test_set.test_cases for r in tc.risk_ids}
    issues += [
        _issue(
            "RISK_HIGH_UNTESTED",
            Severity.WARNING,
            f"High-severity risk {risk.id} ({risk.title}) has no test case referencing it.",
        )
        for risk in analysis.risks
        if risk.severity is Level.HIGH and risk.id not in mitigated
    ]

    if not any(tc.technique in NEGATIVE_TECHNIQUES for tc in test_set.test_cases):
        issues.append(
            _issue(
                "SET_NO_NEGATIVE_TESTS",
                Severity.WARNING,
                "No negative or error-handling test cases in the set.",
            )
        )
    return ValidationReport(
        issues=issues,
        coverage=coverage,
        finding_coverage=build_finding_coverage(analysis.finding_ids, test_set.test_cases),
        risk_coverage=build_risk_coverage(analysis.risk_ids, test_set.test_cases),
        ready_test_case_ids=ready,
        clarification_required_test_case_ids=[
            tc.id for tc in test_set.test_cases if tc.status is Readiness.CLARIFICATION_REQUIRED
        ],
    )
