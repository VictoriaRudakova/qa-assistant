from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from qa_assistant.domain.test_case import TestCaseSet
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
