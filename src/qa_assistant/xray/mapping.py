"""Configurable Xray CSV column mapping.

The production mapping (Xray Cloud vs Data Center, exact headers) is NOT hardcoded: it is
loaded from the JSON file named by ``XRAY_CSV_MAPPING_FILE``. Tests use a synthetic
placeholder mapping under ``tests/fixtures/xray/``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from qa_assistant.domain.base import DomainModel, NonEmptyStr
from qa_assistant.domain.enums import Priority
from qa_assistant.errors import NotConfiguredError


class ColumnSource(StrEnum):
    """Where a CSV cell's value comes from."""

    # Test-level (written on the first row of a test, or every row if configured)
    TEST_CASE_ID = "test_case_id"  # always written on every row: groups steps of one test
    TITLE = "title"
    OBJECTIVE = "objective"
    PRECONDITIONS = "preconditions"
    PRIORITY = "priority"
    LABELS = "labels"
    COMPONENTS = "components"
    STORY_KEY = "story_key"
    CONSTANT = "constant"
    # Step-level (one row per step)
    STEP_NUMBER = "step_number"
    STEP_ACTION = "step_action"
    STEP_DATA = "step_data"
    STEP_EXPECTED_RESULT = "step_expected_result"


STEP_SOURCES = frozenset(
    {
        ColumnSource.STEP_NUMBER,
        ColumnSource.STEP_ACTION,
        ColumnSource.STEP_DATA,
        ColumnSource.STEP_EXPECTED_RESULT,
    }
)


class CsvColumn(DomainModel):
    header: NonEmptyStr
    source: ColumnSource
    value: str | None = Field(default=None, description="Only for source='constant'")

    @model_validator(mode="after")
    def _constant_has_value(self) -> Self:
        if (self.source is ColumnSource.CONSTANT) != (self.value is not None):
            raise ValueError("'value' is required for, and only allowed with, source='constant'")
        return self


class XrayCsvMapping(DomainModel):
    name: NonEmptyStr
    synthetic: bool = Field(
        default=False, description="True for test placeholders that must not be used for import"
    )
    delimiter: Annotated[str, StringConstraints(min_length=1, max_length=1)] = ","
    multi_value_separator: str = Field(
        default=";", description="Joins labels/components within one cell"
    )
    multiline_separator: str = Field(default="\n", description="Joins preconditions")
    encoding: Literal["utf-8", "utf-8-sig"] = "utf-8"
    line_terminator: Literal["\n", "\r\n"] = "\r\n"
    repeat_test_fields_on_every_row: bool = False
    columns: list[CsvColumn] = Field(min_length=1)
    priority_map: dict[Priority, NonEmptyStr] = Field(
        default_factory=lambda: {p: p.value.capitalize() for p in Priority}
    )

    @model_validator(mode="after")
    def _validate_columns(self) -> Self:
        headers = [c.header for c in self.columns]
        if len(headers) != len(set(headers)):
            raise ValueError("column headers must be unique")
        if not any(c.source is ColumnSource.TEST_CASE_ID for c in self.columns):
            raise ValueError("a test_case_id column is required to group step rows")
        missing = set(Priority) - set(self.priority_map)
        if missing:
            raise ValueError(f"priority_map missing: {', '.join(sorted(missing))}")
        return self

    @classmethod
    def from_file(cls, path: Path) -> Self:
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise NotConfiguredError(f"Xray CSV mapping file not found: {path}") from exc
