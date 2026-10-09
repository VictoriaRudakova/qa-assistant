"""Scenario-specific reference data and recorded candidates.

A *scenario* is a synthetic Jira story (its ACs are the authoritative requirements) plus
optional *reference* data that a scenario author has justified for that story: findings an
analyst must raise, ACs that must have an exportable test, behaviour that must stay blocked,
techniques that apply to an AC, planted canaries. Reference checks only run when the scenario
declares them in ``checks``; the universal checks in ``evals.checks`` run for every story.

Reference data is expressed in the generic vocabulary of the domain model (AC ids, finding
kinds, techniques, readiness) so the engine never needs to know what the story is about.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qa_assistant.domain.enums import FindingKind, Technique
from qa_assistant.domain.story import JiraStory

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

ReferenceCheck = Literal[
    "expected_findings",
    "ready_acs",
    "expected_blocked",
    "applicable_techniques",
    "export_readiness",
    "injection_ignored",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindingExpectation(_Model):
    """At least one finding of one of ``kinds`` relating to all of ``related_ac_ids``."""

    kinds: list[FindingKind]
    related_ac_ids: list[str] = Field(default_factory=list)
    why: str = Field(default="", description="Why the story justifies this expectation")


class TechniqueExpectation(_Model):
    """Some case covering each of ``ac_ids`` uses ``technique``."""

    technique: Technique
    ac_ids: list[str]
    why: str = ""


class Reference(_Model):
    expected_findings: list[FindingExpectation] = Field(default_factory=list)
    ready_acs: list[str] | Literal["all"] = Field(
        default_factory=list, description="ACs the story fully specifies: each needs a ready case"
    )
    expected_blocked: list[FindingExpectation] = Field(
        default_factory=list,
        description="Behaviour whose expected result depends on an open question: some "
        "clarification_required case must name such a finding as its open question",
    )
    applicable_techniques: list[TechniqueExpectation] = Field(default_factory=list)
    export_ready: bool | None = None
    canaries: list[str] = Field(
        default_factory=list,
        description="Planted strings that must not appear in ACs, requirements or test cases",
    )
    expect_untrusted_flags: bool = False
    known_risks: list[str] = Field(
        default_factory=list,
        description="For human or LLM review only; not checked deterministically",
    )

    def declares(self) -> set[str]:
        present = {
            "expected_findings": bool(self.expected_findings),
            "ready_acs": bool(self.ready_acs),
            "expected_blocked": bool(self.expected_blocked),
            "applicable_techniques": bool(self.applicable_techniques),
            "export_readiness": self.export_ready is not None,
            "injection_ignored": bool(self.canaries or self.expect_untrusted_flags),
        }
        return {name for name, has in present.items() if has}

    def ac_ids(self) -> set[str]:
        groups = [e.related_ac_ids for e in (*self.expected_findings, *self.expected_blocked)]
        groups += [t.ac_ids for t in self.applicable_techniques]
        if isinstance(self.ready_acs, list):
            groups.append(self.ready_acs)
        return {ac for group in groups for ac in group}


class Scenario(_Model):
    id: str
    title: str
    domain: str = Field(description="Informational label; the engine never reads it")
    measures: list[str]
    story: JiraStory
    checks: list[ReferenceCheck] = Field(
        default_factory=list, description="Reference checks this scenario supports"
    )
    reference: Reference = Field(default_factory=Reference)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        declared, present = set(self.checks), self.reference.declares()
        if declared != present:
            raise ValueError(
                f"checks {sorted(declared)} do not match reference data {sorted(present)}"
            )
        unknown = self.reference.ac_ids() - {ac.id for ac in self.story.acceptance_criteria}
        if unknown:
            raise ValueError(f"reference names ACs the story does not have: {sorted(unknown)}")
        return self


class Candidate(_Model):
    name: str
    description: str
    expected_failed_checks: list[str] = Field(default_factory=list)
    analysis: dict[str, Any]
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    reviewed_test_cases: list[dict[str, Any]] | None = None


def load_scenarios(root: Path = SCENARIOS_DIR) -> list[Scenario]:
    return [
        Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*/scenario.json"))
    ]


def load_candidates(scenario_id: str, root: Path = SCENARIOS_DIR) -> list[Candidate]:
    """Candidates of a scenario. ``"extends": "<name>"`` starts from another candidate;
    ``append_test_cases`` / ``keep_test_cases`` then adjust its designer revision."""
    raw = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / scenario_id / "candidates").glob("*.json"))
    }

    def resolve(name: str) -> dict[str, Any]:
        data = dict(raw[name])
        base_name = data.pop("extends", None)
        if base_name is None:
            return data
        merged = {**resolve(base_name), **data}
        merged.pop("expected_failed_checks", None)
        merged["expected_failed_checks"] = data.get("expected_failed_checks", [])
        cases = list(merged.get("test_cases", []))
        if "keep_test_cases" in data:
            cases = cases[: merged.pop("keep_test_cases")]
        cases += merged.pop("append_test_cases", [])
        merged["test_cases"] = cases
        return merged

    return [Candidate.model_validate({"name": name, **resolve(name)}) for name in raw]
