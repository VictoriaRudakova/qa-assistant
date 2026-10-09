"""Deterministic consistency checks for a submitted :class:`StoryAnalysis`.

These do not judge analysis *quality* (that is the LLM reviewer's job); they catch broken
references that would make downstream traceability wrong, and enforce that the analysis
carries exactly the story's Jira acceptance criteria.
"""

from __future__ import annotations

import re
from collections import defaultdict

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import Severity
from qa_assistant.domain.story import AcceptanceCriterion, JiraStory
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
    if not analysis.acceptance_criteria:
        issues.append(
            ValidationIssue(
                code="ANALYSIS_NO_ACCEPTANCE_CRITERIA",
                severity=Severity.WARNING,
                message="The story has no acceptance criteria; tests can trace only to "
                "findings and risks. Raise this with the product owner.",
                field="acceptance_criteria",
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

    issues += _check_duplicate_acs(
        story.acceptance_criteria if story is not None else analysis.acceptance_criteria,
        analysis,
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
        jira_ids = {ac.id for ac in story.acceptance_criteria}
        for ac_id in sorted(jira_ids - known):
            issues.append(
                ValidationIssue(
                    code="ANALYSIS_DROPPED_AC",
                    severity=Severity.ERROR,
                    message=f"Story acceptance criterion {ac_id} is missing from the analysis.",
                    field="acceptance_criteria",
                )
            )
        for ac_id in sorted(known - jira_ids):
            issues.append(
                ValidationIssue(
                    code="ANALYSIS_NON_JIRA_AC",
                    severity=Severity.ERROR,
                    message=(
                        f"Acceptance criterion {ac_id} is not in Jira. Only Jira acceptance "
                        "criteria are authoritative; record the gap as a finding instead."
                    ),
                    field="acceptance_criteria",
                )
            )
        jira_text = {ac.id: _normalize(ac.text) for ac in story.acceptance_criteria}
        issues += [
            ValidationIssue(
                code="ANALYSIS_AC_TEXT_REPLACED",
                severity=Severity.WARNING,
                message=f"Acceptance criterion {ac.id} was reworded; Jira's wording is stored. "
                "Copy acceptance criteria verbatim.",
                field="acceptance_criteria",
            )
            for ac in analysis.acceptance_criteria
            if ac.id in jira_text and _normalize(ac.text) != jira_text[ac.id]
        ]
    return issues


def _check_duplicate_acs(
    criteria: list[AcceptanceCriterion], analysis: StoryAnalysis
) -> list[ValidationIssue]:
    """Jira criteria with the same wording stay separate ACs; the analysis must say so.

    Merging or dropping one is already an error (ANALYSIS_DROPPED_AC). This warns when no
    finding relates to every criterion of a duplicate group, i.e. nobody asked the PO about it.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for ac in criteria:
        groups[_normalize(ac.text)].append(ac.id)
    issues: list[ValidationIssue] = []
    for ids in groups.values():
        if len(ids) < 2:
            continue
        if any(set(ids) <= set(f.related_ac_ids) for f in analysis.findings):
            continue
        issues.append(
            ValidationIssue(
                code="ANALYSIS_DUPLICATE_AC",
                severity=Severity.WARNING,
                message=f"Acceptance criteria {', '.join(ids)} have the same wording. Keep "
                "them all and add a finding with related_ac_ids covering each of them.",
                field="findings",
            )
        )
    return issues


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.casefold())).strip()
