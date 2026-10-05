"""CSV cell sanitization.

Guards against CSV/formula injection when the export is opened in a spreadsheet, and
removes control characters that break importers. Plain numbers (e.g. boundary test data
like ``-1``) are left untouched.
"""

from __future__ import annotations

import re

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_cell(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _CONTROL_RE.sub("", value)
    if value.startswith(_FORMULA_PREFIXES) and not _NUMBER_RE.match(value):
        return "'" + value
    return value
