from __future__ import annotations

from pydantic import ConfigDict, Field, computed_field

from qa_assistant.domain.base import DomainModel
from qa_assistant.domain.enums import Severity


class ValidationIssue(DomainModel):
    code: str = Field(description="Stable rule code, e.g. AC_NOT_COVERED")
    severity: Severity
    message: str
    test_case_id: str | None = None
    field: str | None = None


class ValidationReport(DomainModel):
    # Output-only model: publish its JSON schema in serialization mode so the computed fields
    # (valid, uncovered_ac_ids) appear in MCP tool output schemas. Without this, clients that
    # validate structured output reject them as additional properties.
    model_config = ConfigDict(json_schema_mode_override="serialization")

    issues: list[ValidationIssue] = Field(default_factory=list)
    coverage: dict[str, list[str]] = Field(
        default_factory=dict, description="Acceptance criterion id -> covering test case ids"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def valid(self) -> bool:
        """True when there are no error-severity issues (warnings do not block export)."""
        return not self.errors

    @computed_field  # type: ignore[prop-decorator]
    @property
    def uncovered_ac_ids(self) -> list[str]:
        return [ac_id for ac_id, tcs in self.coverage.items() if not tcs]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]
