from __future__ import annotations

from typing import Any

import pytest

from qa_assistant.domain.enums import AcceptanceCriterionSource
from qa_assistant.jira.acceptance_criteria import extract_acceptance_criteria
from qa_assistant.jira.text import adf_to_text, wiki_to_text


def text(value: str, *marks: str) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if marks:
        node["marks"] = [{"type": m} for m in marks]
    return node


def para(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(content)}


def item(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "listItem", "content": list(content)}


def doc(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "version": 1, "content": list(content)}


def test_adf_story_with_acceptance_criteria_section() -> None:
    document = doc(
        para(text("As a shopper I want a cart.")),
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Acceptance Criteria")]},
        {
            "type": "bulletList",
            "content": [
                item(para(text("Items can be added."))),
                item(
                    para(text("Totals update.")),
                    para(text("Including tax.")),
                    {"type": "bulletList", "content": [item(para(text("Rounded to cents.")))]},
                ),
            ],
        },
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Notes")]},
        para(text("Out of scope: coupons.")),
    )
    rendered = adf_to_text(document)
    assert rendered == (
        "As a shopper I want a cart.\n\n"
        "## Acceptance Criteria\n\n"
        "- Items can be added.\n"
        "- Totals update.\n"
        "  Including tax.\n"
        "  - Rounded to cents.\n\n"
        "## Notes\n\n"
        "Out of scope: coupons."
    )
    criteria = extract_acceptance_criteria(field_value=None, description=rendered)
    assert [c.text for c in criteria] == [
        "Items can be added.",
        "Totals update.\nIncluding tax.",
        "Rounded to cents.",
    ]
    assert criteria[0].source is AcceptanceCriterionSource.DESCRIPTION


def test_adf_bold_line_acts_as_heading() -> None:
    document = doc(
        para(text("Acceptance criteria", "strong")),
        {
            "type": "orderedList",
            "attrs": {"order": 3},
            "content": [item(para(text("First"))), item(para(text("Second")))],
        },
    )
    rendered = adf_to_text(document)
    assert rendered == "**Acceptance criteria**\n\n3. First\n4. Second"
    criteria = extract_acceptance_criteria(field_value=None, description=rendered)
    assert [c.text for c in criteria] == ["First", "Second"]


def test_adf_task_list() -> None:
    document = doc(
        {
            "type": "taskList",
            "content": [
                {"type": "taskItem", "attrs": {"state": "DONE"}, "content": [text("Done")]},
                {"type": "taskItem", "attrs": {"state": "TODO"}, "content": [text("Open")]},
                {
                    "type": "taskList",
                    "content": [{"type": "taskItem", "content": [text("Nested")]}],
                },
            ],
        }
    )
    assert adf_to_text(document) == "- [x] Done\n- [ ] Open\n  - [ ] Nested"


def test_adf_inline_nodes() -> None:
    document = doc(
        para(
            text("Ask "),
            {"type": "mention", "attrs": {"text": "@Alex Example"}},
            text(" "),
            {"type": "emoji", "attrs": {"shortName": ":smile:"}},
            {"type": "emoji", "attrs": {"text": "!"}},
            {"type": "hardBreak"},
            {"type": "status", "attrs": {"text": "BLOCKED"}},
            text(" "),
            {"type": "inlineCard", "attrs": {"url": "https://docs.example.com/x"}},
            text(" due "),
            {"type": "date", "attrs": {"timestamp": "1790000000000"}},
            {"type": "date", "attrs": {"timestamp": "not-a-number"}},
            {"type": "unknownInline", "content": [text(" end")]},
            text("   ", "strong"),
        )
    )
    assert adf_to_text(document) == (
        "Ask @Alex Example :smile:!\nBLOCKED https://docs.example.com/x due 2026-09-21 end"
    )


def test_adf_blocks_tables_code_and_skipped_nodes() -> None:
    cell = {"type": "tableCell", "content": [para(text("v"))]}
    header = {"type": "tableHeader", "content": [para(text("h"))]}
    document = doc(
        {"type": "panel", "content": [para(text("Inside panel"))]},
        {"type": "codeBlock", "content": [text("x = 1")]},
        {"type": "rule"},
        {"type": "mediaSingle", "content": [{"type": "media"}]},
        {
            "type": "table",
            "content": [
                {"type": "tableRow", "content": [header, header]},
                {"type": "tableRow", "content": [cell, cell]},
                {"type": "tableRow", "content": [{"type": "tableCell", "content": []}]},
            ],
        },
        {"type": "heading", "attrs": {"level": 9}, "content": [text("Odd level")]},
    )
    document["content"].append("not a node")  # ignored
    assert adf_to_text(document) == "Inside panel\n\nx = 1\n\nh | h\nv | v\n\n# Odd level"


@pytest.mark.parametrize("value", [None, "plain", 42, []])
def test_adf_non_mapping_is_empty(value: Any) -> None:
    assert adf_to_text(value) == ""


def test_adf_single_node_without_doc() -> None:
    assert adf_to_text(para(text("Only a paragraph"))) == "Only a paragraph"
    assert adf_to_text({"type": "paragraph", "content": "broken"}) == ""


def test_wiki_markup() -> None:
    markup = (
        "h2. Acceptance Criteria\r\n"
        "# First\r\n"
        "## Nested numbered\n"
        "* Bullet with [a link|https://docs.example.com]\n"
        "** Nested bullet [https://docs.example.com/raw]\n"
        "- Dash bullet\n"
        "{code:java}\n"
        "int x = 1;\n"
        "{code}\n"
        "Line one\\\\Line two\n"
        "||Col A||Col B||\n"
        "|a|b|\n"
        "\n\n\n"
        "*Bold heading*"
    )
    assert wiki_to_text(markup) == (
        "h2. Acceptance Criteria\n"
        "1. First\n"
        "  1. Nested numbered\n"
        "- Bullet with a link\n"
        "  - Nested bullet https://docs.example.com/raw\n"
        "- Dash bullet\n"
        "int x = 1;\n"
        "Line one\nLine two\n"
        "Col A | Col B\n"
        "a | b\n\n"
        "*Bold heading*"
    )
    criteria = extract_acceptance_criteria(field_value=None, description=wiki_to_text(markup))
    assert criteria[0].text == "First"
