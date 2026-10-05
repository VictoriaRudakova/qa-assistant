"""QA analysis of a story, produced by the LLM and submitted as structured data."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, computed_field, model_validator

from qa_assistant.domain.base import (
    AcceptanceCriterionId,
    DomainModel,
    FindingId,
    IssueKey,
    NonEmptyStr,
    RiskId,
)
from qa_assistant.domain.enums import FindingKind, Level, RiskCategory, level_score
from qa_assistant.domain.story import AcceptanceCriterion


def risk_severity(likelihood: Level, impact: Level) -> Level:
    """Deterministic likelihood x impact matrix (1..3 each)."""
    score = level_score(likelihood) * level_score(impact)
    if score >= 6:
        return Level.HIGH
    if score >= 3:
        return Level.MEDIUM
    return Level.LOW


class Risk(DomainModel):
    id: RiskId
    title: NonEmptyStr
    description: NonEmptyStr
    category: RiskCategory
    likelihood: Level
    impact: Level
    related_ac_ids: list[AcceptanceCriterionId] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> Level:
        return risk_severity(self.likelihood, self.impact)


class Finding(DomainModel):
    """An ambiguity, gap, inconsistency or open question about the story."""

    id: FindingId
    kind: FindingKind
    text: NonEmptyStr
    related_ac_ids: list[AcceptanceCriterionId] = Field(default_factory=list)


class StoryAnalysis(DomainModel):
    story_key: IssueKey
    summary: NonEmptyStr = Field(description="One-paragraph QA-oriented summary of the story")
    requirements: list[NonEmptyStr] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        min_length=1,
        description="Normalized ACs: those from Jira plus any inferred ones (source='inferred')",
    )
    findings: list[Finding] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    assumptions: list[NonEmptyStr] = Field(default_factory=list)
    out_of_scope: list[NonEmptyStr] = Field(default_factory=list)
    schema_version: Literal["1"] = "1"

    @model_validator(mode="after")
    def _ids_unique(self) -> Self:
        for label, ids in (
            ("acceptance criterion", [ac.id for ac in self.acceptance_criteria]),
            ("risk", [r.id for r in self.risks]),
            ("finding", [f.id for f in self.findings]),
        ):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label} ids: {', '.join(duplicates)}")
        return self

    @property
    def ac_ids(self) -> set[str]:
        return {ac.id for ac in self.acceptance_criteria}

    @property
    def risk_ids(self) -> set[str]:
        return {r.id for r in self.risks}
