from __future__ import annotations

import pytest

from qa_assistant.xray.sanitize import sanitize_cell


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("-2+3", "'-2+3"),
        ("@SUM(1)", "'@SUM(1)"),
        ("\tTabbed", "'\tTabbed"),
        ("Plain text", "Plain text"),
        ("a = b", "a = b"),
        ("", ""),
    ],
)
def test_formula_prefixes_are_neutralized(value: str, expected: str) -> None:
    assert sanitize_cell(value) == expected


@pytest.mark.parametrize("number", ["-1", "+5", "-0.5", "-3,25", "42"])
def test_plain_numbers_are_kept_for_boundary_data(number: str) -> None:
    assert sanitize_cell(number) == number


def test_line_endings_normalized_and_control_chars_removed() -> None:
    assert sanitize_cell("line1\r\nline2\rline3\x00\x07") == "line1\nline2\nline3"


def test_leading_carriage_return_is_normalized_not_escaped() -> None:
    assert sanitize_cell("\rvalue") == "\nvalue"
