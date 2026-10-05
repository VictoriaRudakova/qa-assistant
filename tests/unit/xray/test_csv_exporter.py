"""Golden-file tests for the mapping-driven exporter.

Regenerate the golden file after an intentional change with:
    UPDATE_GOLDEN=1 uv run pytest tests/unit/xray/test_csv_exporter.py
and review the diff before committing.
"""

from __future__ import annotations

import csv
import io
import os

from qa_assistant.domain.test_case import TestCaseSet
from qa_assistant.xray.csv_exporter import MappedXrayCsvExporter
from qa_assistant.xray.mapping import XrayCsvMapping
from qa_assistant.xray.ports import XrayCsvExporter
from tests.support import FIXTURES

GOLDEN = FIXTURES / "xray" / "DEMO-101.synthetic.csv"


def render(mapping: XrayCsvMapping, test_set: TestCaseSet) -> str:
    exporter: XrayCsvExporter = MappedXrayCsvExporter(mapping)
    return exporter.render(test_set).text


def test_reports_its_own_row_count(
    synthetic_mapping: XrayCsvMapping, test_set: TestCaseSet
) -> None:
    rendered = MappedXrayCsvExporter(synthetic_mapping).render(test_set)
    parsed_rows = list(csv.reader(io.StringIO(rendered.text)))
    assert rendered.rows == len(parsed_rows) - 1 == 9  # minus header


def test_matches_golden_file(synthetic_mapping: XrayCsvMapping, test_set: TestCaseSet) -> None:
    output = render(synthetic_mapping, test_set)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_bytes(output.encode("utf-8"))
    assert output == GOLDEN.read_bytes().decode("utf-8")


def test_is_deterministic(synthetic_mapping: XrayCsvMapping, test_set: TestCaseSet) -> None:
    assert render(synthetic_mapping, test_set) == render(synthetic_mapping, test_set)


def test_one_row_per_step_with_test_fields_on_first_row(
    synthetic_mapping: XrayCsvMapping, test_set: TestCaseSet
) -> None:
    rows = list(csv.DictReader(io.StringIO(render(synthetic_mapping, test_set))))
    assert len(rows) == sum(len(tc.steps) for tc in test_set.test_cases)

    tc2 = [r for r in rows if r["TCID"] == "TC-002"]
    assert [r["Step"] for r in tc2] == ["1", "2", "3"]
    assert tc2[0]["Summary"] == test_set.test_cases[1].title
    assert tc2[0]["Priority"] == "High"
    assert tc2[0]["Test Type"] == "Manual"
    assert tc2[0]["Preconditions"].splitlines() == test_set.test_cases[1].preconditions
    assert all(r["Summary"] == "" for r in tc2[1:])
    assert tc2[1]["Data"] == "qa.user@example.com"


def test_formula_like_step_data_is_escaped(
    synthetic_mapping: XrayCsvMapping, test_set: TestCaseSet
) -> None:
    rows = list(csv.DictReader(io.StringIO(render(synthetic_mapping, test_set))))
    assert any(r["Data"].startswith("'=SUM(A1)") for r in rows)


def test_repeat_fields_delimiter_and_line_endings(
    synthetic_mapping: XrayCsvMapping, test_set: TestCaseSet
) -> None:
    mapping = synthetic_mapping.model_copy(
        update={"repeat_test_fields_on_every_row": True, "delimiter": ";", "line_terminator": "\n"}
    )
    output = render(mapping, test_set)
    assert "\r\n" not in output.replace('"\r\n', "")
    rows = list(csv.DictReader(io.StringIO(output), delimiter=";"))
    assert all(r["Summary"] for r in rows)
    assert {r["Labels"] for r in rows if r["TCID"] == "TC-003"} == {"password-reset;security"}
