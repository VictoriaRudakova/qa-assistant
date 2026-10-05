"""Manual test case model: the single source of truth every exporter reads from."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from qa_assistant.domain.base import (
    AcceptanceCriterionId,
    DomainModel,
    IssueKey,
    NonEmptyStr,
    RiskId,
    RunId,
    TestCaseId,
)
from qa_assistant.domain.enums import Priority, Technique

Label = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\S{1,255}$"),
    Field(description="Jira label: no whitespace"),
]


class TestStep(DomainModel):
    __test__: ClassVar[bool] = False  # not a pytest test class

    action: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3)]
    data: str | None = Field(default=None, description="Test data used by this step")
    expected_result: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3)]


class TestCaseDraft(DomainModel):
    """A test case as submitted by the LLM (no id yet)."""

    __test__: ClassVar[bool] = False

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
    objective: NonEmptyStr = Field(description="What this test verifies and why")
    preconditions: list[NonEmptyStr] = Field(default_factory=list)
    steps: list[TestStep] = Field(min_length=1, max_length=50)
    priority: Priority
    technique: Technique
    covers: list[AcceptanceCriterionId] = Field(
        min_length=1, description="Acceptance criteria this test verifies"
    )
    risk_ids: list[RiskId] = Field(default_factory=list, description="Risks this test mitigates")
    labels: list[Label] = Field(default_factory=list)
    components: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_refs(self) -> Self:
        for name in ("covers", "risk_ids", "labels", "components"):
            values: list[str] = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} contains duplicates")
        return self


class TestCase(TestCaseDraft):
    """A persisted test case with a stable id within its run."""

    __test__: ClassVar[bool] = False

    id: TestCaseId


class TestCaseSet(DomainModel):
    """One revision of the test cases of a run."""

    __test__: ClassVar[bool] = False

    run_id: RunId
    story_key: IssueKey
    revision: int = Field(ge=1)
    created_at: datetime
    test_cases: list[TestCase] = Field(min_length=1)
    schema_version: Literal["1"] = "1"

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [tc.id for tc in self.test_cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate test case ids")
        return self
