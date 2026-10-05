"""Deterministic consistency checks for a submitted :class:`StoryAnalysis`.

These do not judge analysis *quality* (that is the LLM reviewer's job); they catch broken
references that would make downstream traceability wrong.
"""

from __future__ import annotations

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Severity
from qa_assistant.domain.story import JiraStory
from qa_assistant.domain.validation import ValidationIssue


def check_analysis(
    analysis: StoryAnalysis, story: JiraStory | None = None
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known = analysis.ac_ids

    for risk in analysis.risks:
        for ac_id in sorted(set(risk.related_ac_ids) - known):
            issues.append(
                ValidationIssue(
                    code="ANALYSIS_UNKNOWN_AC",
                    severity=Severity.ERROR,
                    message=f"Risk {risk.id} references unknown acceptance criterion {ac_id}.",
                    field="risks",
                )
            )
    for finding in analysis.findings:
        for ac_id in sorted(set(finding.related_ac_ids) - known):
            issues.append(
                ValidationIssue(
                    code="ANALYSIS_UNKNOWN_AC",
                    severity=Severity.ERROR,
                    message=(
                        f"Finding {finding.id} references unknown acceptance criterion {ac_id}."
                    ),
                    field="findings",
                )
            )
    if not analysis.risks:
        issues.append(
            ValidationIssue(
                code="ANALYSIS_NO_RISKS",
                severity=Severity.WARNING,
                message="No risks identified; confirm this is intentional.",
                field="risks",
            )
        )

    if story is not None:
        if story.key != analysis.story_key:
            issues.append(
                ValidationIssue(
                    code="ANALYSIS_STORY_MISMATCH",
                    severity=Severity.ERROR,
                    message=f"Analysis is for {analysis.story_key} but story is {story.key}.",
                    field="story_key",
                )
            )
        for ac_id in sorted({ac.id for ac in story.acceptance_criteria} - known):
            issues.append(
                ValidationIssue(
                    code="ANALYSIS_DROPPED_AC",
                    severity=Severity.WARNING,
                    message=f"Story acceptance criterion {ac_id} is missing from the analysis.",
                    field="acceptance_criteria",
                )
            )
    return issues
