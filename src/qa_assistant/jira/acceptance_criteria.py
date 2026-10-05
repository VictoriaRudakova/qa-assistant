"""Deterministic acceptance-criteria extraction.

Source priority:
1. The configured custom field (``JIRA_ACCEPTANCE_CRITERIA_FIELD``), if it has content.
2. Otherwise an "Acceptance Criteria" section of the description.

Input text convention (the Cloud/DC adapters must normalize ADF / wiki markup to this):
* headings:  ``# Title`` .. ``###### Title`` or wiki style ``h1. Title``; a line that is only
  bold text (``**Title**`` / ``*Title*``) also counts as a heading;
* bullets:   ``- item``, ``* item``, ``• item``, numbered ``1. item`` / ``1) item``;
  checkbox markers ``[ ]`` / ``[x]`` are stripped;
* Gherkin:   ``Scenario:`` / ``Given`` / ``When`` / ``Then`` / ``And`` / ``But`` lines are
  grouped into one criterion per scenario.

Criteria are renumbered AC-1..AC-n, so an author's own leading label (``AC1.``, ``AC1:``,
``AC-1.``, ``AC-1:``) is stripped from the criterion text.
"""

from __future__ import annotations

import re

from qa_assistant.domain.enums import AcceptanceCriterionSource
from qa_assistant.domain.story import AcceptanceCriterion

_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s+|h[1-6]\.\s+)(?P<title>.+?)\s*$", re.IGNORECASE)
_BOLD_LINE_RE = re.compile(r"^\s*(\*{1,2})(?P<title>[^*]+?)\1\s*:?\s*$")
_AC_TITLE_RE = re.compile(r"^(acceptance\s+criteria|a\.?c\.?)\s*:?$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?P<text>.+)$")
_CHECKBOX_RE = re.compile(r"^\[[ xX]?\]\s*")
_SCENARIO_RE = re.compile(r"^\s*scenario(?:\s+outline)?\s*:", re.IGNORECASE)
_GIVEN_RE = re.compile(r"^\s*given\b", re.IGNORECASE)
_STEP_RE = re.compile(r"^\s*(?:when|then|and|but)\b", re.IGNORECASE)
_THEN_RE = re.compile(r"^\s*then\b", re.IGNORECASE)
_LABEL_RE = re.compile(r"^AC[-\s]?\d+\s*[.:]\s*", re.IGNORECASE)


def extract_acceptance_criteria(
    *, field_value: str | None, description: str
) -> list[AcceptanceCriterion]:
    """Extract and number acceptance criteria (AC-1..AC-n)."""
    if field_value and field_value.strip():
        texts = parse_criteria_items(field_value)
        source = AcceptanceCriterionSource.FIELD
    else:
        texts = parse_criteria_items(find_acceptance_criteria_section(description))
        source = AcceptanceCriterionSource.DESCRIPTION
    texts = [text for raw in texts if (text := strip_criterion_label(raw))]
    return [
        AcceptanceCriterion(id=f"AC-{n}", text=text, source=source)
        for n, text in enumerate(texts, start=1)
    ]


def strip_criterion_label(text: str) -> str:
    """Remove a leading author label such as ``AC1.`` / ``AC-1:`` from a criterion."""
    return _LABEL_RE.sub("", text.strip(), count=1).strip()


def _heading_title(line: str) -> str | None:
    match = _HEADING_RE.match(line) or _BOLD_LINE_RE.match(line)
    return match.group("title").strip() if match else None


def find_acceptance_criteria_section(description: str) -> str:
    """Return the body of the first "Acceptance Criteria" section, or ``""``."""
    lines = description.splitlines()
    for index, line in enumerate(lines):
        title = _heading_title(line)
        if title is None:
            # Plain "Acceptance criteria:" line acts as a heading too.
            if _AC_TITLE_RE.match(line.strip()):
                title = line.strip()
            else:
                continue
        if not _AC_TITLE_RE.match(title):
            continue
        body: list[str] = []
        for following in lines[index + 1 :]:
            if _heading_title(following) is not None and not _BULLET_RE.match(following):
                break
            body.append(following)
        return "\n".join(body)
    return ""


def parse_criteria_items(text: str) -> list[str]:
    """Split a block of text into individual criteria.

    A blank line closes the current criterion. Gherkin lines stay together until the next
    ``Scenario:`` or a ``Given`` that follows a ``Then``.
    """
    items: list[list[str]] = []
    current: list[str] | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            current = None
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            line = _CHECKBOX_RE.sub("", bullet.group("text")).strip()
            if not line:
                continue
        in_gherkin = current is not None and _is_gherkin_block(current)

        if _SCENARIO_RE.match(line):
            starts_new = True
        elif _GIVEN_RE.match(line):
            # A Given after a Then begins the next scenario.
            starts_new = not in_gherkin or any(_THEN_RE.match(p) for p in current or [])
        elif _STEP_RE.match(line) and in_gherkin:
            starts_new = False
        else:
            starts_new = bool(bullet) or current is None

        if starts_new or current is None:
            current = [line]
            items.append(current)
        else:
            current.append(line)
    return ["\n".join(parts) for parts in items]


def _is_gherkin_block(lines: list[str]) -> bool:
    return bool(_SCENARIO_RE.match(lines[0]) or _GIVEN_RE.match(lines[0]))
