from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qa_assistant.errors import NotConfiguredError
from qa_assistant.xray.mapping import XrayCsvMapping
from tests.support import load_json


@pytest.fixture
def mapping_data() -> dict[str, Any]:
    data: dict[str, Any] = load_json("xray/synthetic_mapping.json")
    return data


def test_synthetic_mapping_loads(synthetic_mapping: XrayCsvMapping) -> None:
    assert synthetic_mapping.synthetic
    assert synthetic_mapping.columns[0].header == "TCID"


def test_missing_file_is_not_configured(tmp_path: Path) -> None:
    with pytest.raises(NotConfiguredError, match="not found"):
        XrayCsvMapping.from_file(tmp_path / "missing.json")


def test_requires_test_case_id_column(mapping_data: dict[str, Any]) -> None:
    mapping_data["columns"] = [c for c in mapping_data["columns"] if c["source"] != "test_case_id"]
    with pytest.raises(ValidationError, match="test_case_id column is required"):
        XrayCsvMapping.model_validate(mapping_data)


def test_headers_must_be_unique(mapping_data: dict[str, Any]) -> None:
    mapping_data["columns"].append({"header": "TCID", "source": "title"})
    with pytest.raises(ValidationError, match="unique"):
        XrayCsvMapping.model_validate(mapping_data)


def test_priority_map_must_be_complete(mapping_data: dict[str, Any]) -> None:
    del mapping_data["priority_map"]["low"]
    with pytest.raises(ValidationError, match="priority_map missing: low"):
        XrayCsvMapping.model_validate(mapping_data)


@pytest.mark.parametrize(
    "column",
    [
        {"header": "X", "source": "constant"},
        {"header": "X", "source": "title", "value": "v"},
    ],
)
def test_constant_value_rules(mapping_data: dict[str, Any], column: dict[str, str]) -> None:
    mapping_data["columns"].append(column)
    with pytest.raises(ValidationError, match="'value' is required"):
        XrayCsvMapping.model_validate(mapping_data)


def test_rejects_multi_char_delimiter(mapping_data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        XrayCsvMapping.model_validate({**mapping_data, "delimiter": ";;"})
