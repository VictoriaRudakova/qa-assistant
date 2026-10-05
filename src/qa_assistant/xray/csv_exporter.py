"""Mapping-driven Xray CSV exporter.

Layout: one row per test step; all rows of a test share the ``test_case_id`` column.
Test-level columns are filled on the first row of each test (or on every row when the
mapping sets ``repeat_test_fields_on_every_row``).
"""

from __future__ import annotations

import csv
import io

from qa_assistant.domain.test_case import TestCase, TestCaseSet, TestStep
from qa_assistant.xray.mapping import STEP_SOURCES, ColumnSource, CsvColumn, XrayCsvMapping
from qa_assistant.xray.ports import RenderedCsv
from qa_assistant.xray.sanitize import sanitize_cell


class MappedXrayCsvExporter:
    def __init__(self, mapping: XrayCsvMapping) -> None:
        self._mapping = mapping

    @property
    def mapping(self) -> XrayCsvMapping:
        return self._mapping

    def render(self, test_set: TestCaseSet) -> RenderedCsv:
        buffer = io.StringIO()
        writer = csv.writer(
            buffer,
            delimiter=self._mapping.delimiter,
            lineterminator=self._mapping.line_terminator,
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writerow([column.header for column in self._mapping.columns])
        rows = 0
        for tc in test_set.test_cases:
            for number, step in enumerate(tc.steps, start=1):
                writer.writerow(self._row(test_set.story_key, tc, number, step))
                rows += 1
        return RenderedCsv(text=buffer.getvalue(), rows=rows)

    def _row(self, story_key: str, tc: TestCase, number: int, step: TestStep) -> list[str]:
        include_test_fields = number == 1 or self._mapping.repeat_test_fields_on_every_row
        row: list[str] = []
        for column in self._mapping.columns:
            if column.source in STEP_SOURCES:
                value = self._step_value(column.source, number, step)
            elif column.source is ColumnSource.TEST_CASE_ID or include_test_fields:
                value = self._test_value(column, story_key, tc)
            else:
                value = ""
            row.append(sanitize_cell(value))
        return row

    def _test_value(self, column: CsvColumn, story_key: str, tc: TestCase) -> str:
        m = self._mapping
        match column.source:
            case ColumnSource.TEST_CASE_ID:
                return tc.id
            case ColumnSource.TITLE:
                return tc.title
            case ColumnSource.OBJECTIVE:
                return tc.objective
            case ColumnSource.PRECONDITIONS:
                return m.multiline_separator.join(tc.preconditions)
            case ColumnSource.PRIORITY:
                return m.priority_map[tc.priority]
            case ColumnSource.LABELS:
                return m.multi_value_separator.join(tc.labels)
            case ColumnSource.COMPONENTS:
                return m.multi_value_separator.join(tc.components)
            case ColumnSource.STORY_KEY:
                return story_key
            case ColumnSource.CONSTANT:
                return column.value or ""
            case _:  # pragma: no cover - step sources are handled by the caller
                raise AssertionError(f"not a test-level source: {column.source}")

    @staticmethod
    def _step_value(source: ColumnSource, number: int, step: TestStep) -> str:
        match source:
            case ColumnSource.STEP_NUMBER:
                return str(number)
            case ColumnSource.STEP_ACTION:
                return step.action
            case ColumnSource.STEP_DATA:
                return step.data or ""
            case ColumnSource.STEP_EXPECTED_RESULT:
                return step.expected_result
            case _:  # pragma: no cover
                raise AssertionError(f"not a step source: {source}")
