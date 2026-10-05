from __future__ import annotations

import pytest

from qa_assistant.domain.enums import AcceptanceCriterionSource
from qa_assistant.domain.story import JiraStory
from qa_assistant.jira.acceptance_criteria import (
    extract_acceptance_criteria,
    find_acceptance_criteria_section,
    parse_criteria_items,
    strip_criterion_label,
)


def texts(field_value: str | None, description: str) -> list[str]:
    return [
        ac.text
        for ac in extract_acceptance_criteria(field_value=field_value, description=description)
    ]


def test_field_value_takes_priority_over_description() -> None:
    acs = extract_acceptance_criteria(
        field_value="- From field",
        description="## Acceptance Criteria\n- From description",
    )
    assert [(ac.id, ac.text, ac.source) for ac in acs] == [
        ("AC-1", "From field", AcceptanceCriterionSource.FIELD)
    ]


@pytest.mark.parametrize("field_value", [None, "", "   \n "])
def test_falls_back_to_description_when_field_empty(field_value: str | None) -> None:
    acs = extract_acceptance_criteria(
        field_value=field_value, description="## Acceptance Criteria\n- One\n- Two"
    )
    assert [ac.text for ac in acs] == ["One", "Two"]
    assert {ac.source for ac in acs} == {AcceptanceCriterionSource.DESCRIPTION}


@pytest.mark.parametrize(
    "heading",
    [
        "## Acceptance Criteria",
        "# acceptance criteria:",
        "h3. Acceptance Criteria",
        "**Acceptance Criteria**",
        "*Acceptance criteria:*",
        "Acceptance Criteria:",
        "### AC",
    ],
)
def test_recognizes_heading_styles(heading: str) -> None:
    description = f"Intro text\n{heading}\n- First\n- Second\n## Notes\n- Not an AC"
    assert texts(None, description) == ["First", "Second"]


def test_section_ends_at_next_heading() -> None:
    description = "## Acceptance Criteria\n1. One\n2) Two\nh2. Out of scope\n- Three"
    assert find_acceptance_criteria_section(description).strip() == "1. One\n2) Two"


def test_no_section_returns_no_criteria() -> None:
    assert texts(None, "Just a description.\n- bullet but no AC heading") == []


def test_bullets_numbers_and_checkboxes() -> None:
    items = parse_criteria_items("- [ ] Unchecked\n* [x] Checked\n• Dot\n3. Numbered")
    assert items == ["Unchecked", "Checked", "Dot", "Numbered"]


def test_continuation_lines_join_previous_item() -> None:
    assert parse_criteria_items("- First line\n  continues here\n- Second") == [
        "First line\ncontinues here",
        "Second",
    ]


def test_blank_line_separates_paragraph_criteria() -> None:
    assert parse_criteria_items("Paragraph one.\n\nParagraph two.") == [
        "Paragraph one.",
        "Paragraph two.",
    ]


def test_gherkin_scenarios_grouped() -> None:
    text = (
        "Scenario: Valid login\n"
        "Given a registered user\n"
        "When they sign in\n"
        "Then the dashboard is shown\n"
        "And a welcome message appears\n"
        "Scenario: Locked account\n"
        "Given a locked user\n"
        "Then an error is shown"
    )
    items = parse_criteria_items(text)
    assert len(items) == 2
    assert items[0].startswith("Scenario: Valid login")
    assert items[0].endswith("And a welcome message appears")
    assert items[1].splitlines() == [
        "Scenario: Locked account",
        "Given a locked user",
        "Then an error is shown",
    ]


def test_given_after_then_starts_new_criterion() -> None:
    text = "Given A\nWhen B\nThen C\nGiven D\nThen E"
    assert parse_criteria_items(text) == ["Given A\nWhen B\nThen C", "Given D\nThen E"]


def test_bulleted_gherkin_steps_stay_together() -> None:
    text = "- Given a cart with 1 item\n- When I remove it\n- Then the cart is empty"
    assert parse_criteria_items(text) == [
        "Given a cart with 1 item\nWhen I remove it\nThen the cart is empty"
    ]


def test_fixture_story_criteria_match_extraction(story: JiraStory) -> None:
    """The synthetic story's stored ACs are exactly what extraction yields."""
    extracted = extract_acceptance_criteria(field_value=None, description=story.description)
    assert extracted == story.acceptance_criteria


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AC1. A customer can add a product.", "A customer can add a product."),
        ("AC1: A customer can add a product.", "A customer can add a product."),
        ("AC-1. A customer can add a product.", "A customer can add a product."),
        ("AC-1: A customer can add a product.", "A customer can add a product."),
        ("ac 12 :  Lower case, spaced", "Lower case, spaced"),
        ("AC1.\nLabel on its own line", "Label on its own line"),
        ("ACCOUNT is locked after 3 attempts", "ACCOUNT is locked after 3 attempts"),
        ("AC1 without punctuation stays", "AC1 without punctuation stays"),
        ("Total AC1: is not a leading label", "Total AC1: is not a leading label"),
        ("AC-2:", ""),
    ],
)
def test_strip_criterion_label(raw: str, expected: str) -> None:
    assert strip_criterion_label(raw) == expected


def test_labels_are_stripped_and_label_only_items_dropped() -> None:
    acs = extract_acceptance_criteria(
        field_value=None,
        description=(
            "Acceptance Criteria\n\nAC1. Add an in-stock product.\n\nAC-2:\n\n"
            "AC-3: Remove a product."
        ),
    )
    assert [(ac.id, ac.text) for ac in acs] == [
        ("AC-1", "Add an in-stock product."),
        ("AC-2", "Remove a product."),
    ]
