"""Shared base model and constrained identifier types."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class DomainModel(BaseModel):
    """Strict base for every domain model.

    ``extra="forbid"`` matters: LLM-produced artifacts must not smuggle in unknown fields.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        """Computed fields are serialized but always re-derived, never accepted as input.

        This keeps JSON round-trips working under ``extra="forbid"`` and stops a caller from
        overriding a deterministic value (e.g. a risk's severity).
        """
        if isinstance(data, dict) and cls.model_computed_fields:
            return {k: v for k, v in data.items() if k not in cls.model_computed_fields}
        return data


IssueKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9_]+-[1-9]\d*$"),
    Field(description="Jira issue key, e.g. DEMO-123"),
]
AcceptanceCriterionId = Annotated[
    str, StringConstraints(pattern=r"^AC-[1-9]\d*$"), Field(description="e.g. AC-1")
]
RiskId = Annotated[str, StringConstraints(pattern=r"^R-[1-9]\d*$"), Field(description="e.g. R-1")]
FindingId = Annotated[
    str, StringConstraints(pattern=r"^F-[1-9]\d*$"), Field(description="e.g. F-1")
]
TestCaseId = Annotated[
    str, StringConstraints(pattern=r"^TC-\d{3,}$"), Field(description="e.g. TC-001")
]
RunId = Annotated[
    str,
    StringConstraints(pattern=r"^\d{8}T\d{6}Z-[0-9a-f]{6}$"),
    Field(description="Run identifier, e.g. 20261005T154400Z-a1b2c3"),
]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
