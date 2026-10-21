from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from qa_assistant.domain.test_case import TestCaseSet
from qa_assistant.domain.xray import XrayTest
from qa_assistant.xray.mapping import XrayCsvMapping


@dataclass(frozen=True)
class RenderedCsv:
    text: str
    rows: int  # data rows, excluding the header


class XrayCsvExporter(Protocol):
    """Renders validated test cases to Xray-importable CSV text. Must be deterministic:
    the same input and mapping always produce byte-identical output."""

    @property
    def mapping(self) -> XrayCsvMapping: ...

    def render(self, test_set: TestCaseSet) -> RenderedCsv: ...


class XrayTestReader(Protocol):
    """Read-only access to Xray Tests in the configured Jira project."""

    def get_test(self, issue_key: str, *, step_offset: int = 0) -> XrayTest:
        """One Test with its steps (from ``step_offset``) and requirements. Raises
        ``NotFoundError`` if the key is outside the project or is not a visible Test."""
        ...
