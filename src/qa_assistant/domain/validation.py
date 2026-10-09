from __future__ import annotations

from pydantic import ConfigDict, Field, computed_field

from qa_assistant.domain.base import DomainModel, RunId
from qa_assistant.domain.enums import Severity


class ValidationIssue(DomainModel):
    code: str = Field(description="Stable rule code, e.g. AC_NOT_COVERED")
    severity: Severity
    message: str
    test_case_id: str | None = None
    field: str | None = None


class ValidationReport(DomainModel):
    # Output-only model: publish its JSON schema in serialization mode so the computed fields
    # (valid, export_ready, uncovered_ac_ids) appear in MCP tool output schemas. Without this,
    # clients that validate structured output reject them as additional properties.
    model_config = ConfigDict(json_schema_mode_override="serialization")

    issues: list[ValidationIssue] = Field(default_factory=list)
    coverage: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Authoritative Jira acceptance criterion id -> covering test case ids",
    )
    finding_coverage: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Finding (requirement gap / question) id -> test case ids exploring it "
        "or waiting on it. Kept separate from acceptance criterion coverage.",
    )
    risk_coverage: dict[str, list[str]] = Field(
        default_factory=dict, description="Risk id -> test case ids mitigating it"
    )
    ready_test_case_ids: list[str] = Field(default_factory=list)
    clarification_required_test_case_ids: list[str] = Field(
        default_factory=list,
        description="Cases whose expected behaviour depends on an unanswered question",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def valid(self) -> bool:
        """True when there are no error-severity issues (warnings do not block export)."""
        return not self.errors

    @computed_field  # type: ignore[prop-decorator]
    @property
    def export_ready(self) -> bool:
        """Final export validation: valid and no case still needs clarification."""
        return self.valid and not self.clarification_required_test_case_ids

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


class CoverageReport(DomainModel):
    """Traceability of one revision, without validation issues.

    Authoritative coverage (Jira acceptance criteria) and inferred coverage (findings and
    risks the analyst identified) are reported separately: covering a gap or a risk never
    counts towards acceptance criterion coverage.
    """

    model_config = ConfigDict(json_schema_mode_override="serialization")

    run_id: RunId
    revision: int
    acceptance_criteria: dict[str, list[str]] = Field(
        description="Authoritative Jira acceptance criterion id -> covering test case ids"
    )
    acceptance_criteria_ready: dict[str, list[str]] = Field(
        description="Jira acceptance criterion id -> covering test cases that are ready"
    )
    findings: dict[str, list[str]] = Field(
        description="Inferred: finding (gap / question) id -> test case ids exploring it"
    )
    risks: dict[str, list[str]] = Field(
        description="Inferred: risk id -> test case ids mitigating it"
    )
    ready_test_case_ids: list[str]
    clarification_required_test_case_ids: list[str]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def uncovered_ac_ids(self) -> list[str]:
        return [ac_id for ac_id, tcs in self.acceptance_criteria.items() if not tcs]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ac_ids_without_ready_test(self) -> list[str]:
        return [ac_id for ac_id, tcs in self.acceptance_criteria_ready.items() if not tcs]
