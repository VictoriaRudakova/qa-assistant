"""Score aggregation and reporting.

``ASPECTS`` is the honest map from quality aspects to the deterministic checks that measure
them. An aspect with no check (or only a partial one) names what still needs human or
LLM-judge review; the scorecard prints that list so nothing is claimed as measured that is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict

from evals.checks import CHECKS, CheckResult, Dimension

DIMENSIONS: tuple[Dimension, ...] = get_args(Dimension)


@dataclass(frozen=True)
class Aspect:
    dimension: Dimension
    name: str
    checks: tuple[str, ...]
    needs_judgment: str = ""  # what a deterministic check cannot decide


ASPECTS: tuple[Aspect, ...] = (
    Aspect("requirements", "authoritative AC preservation", ("ac_preserved", "ac_text_preserved")),
    Aspect(
        "requirements",
        "invented requirements",
        ("ac_preserved", "unsupported_assertions"),
        "invented free-text `requirements` or assumptions in the analysis",
    ),
    Aspect(
        "requirements", "missing or altered requirements", ("ac_preserved", "ac_text_preserved")
    ),
    Aspect(
        "requirements",
        "ambiguities and conflicts identified",
        ("expected_findings", "duplicate_acs_raised"),
        "findings beyond the scenario's reference list: are they real, relevant, well phrased",
    ),
    Aspect("requirements", "assumptions", (), "whether stated assumptions are reasonable"),
    Aspect("test_design", "requirement traceability", ("traceability",)),
    Aspect(
        "test_design",
        "AC coverage",
        ("ac_coverage",),
        "whether a covering case verifies the AC meaningfully rather than just referencing it",
    ),
    Aspect(
        "test_design",
        "positive and negative coverage",
        ("negative_coverage", "ac_coverage"),
        "whether the negative cases target the meaningful invalid partitions",
    ),
    Aspect(
        "test_design",
        "boundary and state-transition coverage",
        ("applicable_techniques",),
        "applicability on stories without reference data",
    ),
    Aspect(
        "test_design",
        "risk traceability",
        ("high_risk_coverage",),
        "whether a case tagged with a risk would actually detect it",
    ),
    Aspect(
        "test_design",
        "redundancy",
        ("redundancy",),
        "cases that verify the same behaviour in different words",
    ),
    Aspect(
        "test_design",
        "observable expected results",
        ("observable_results",),
        "results that avoid the vague phrase list but are still unverifiable",
    ),
    Aspect(
        "test_design",
        "unsupported test assertions",
        ("unsupported_assertions",),
        "a case covering an AC that silently asserts a guessed answer",
    ),
    Aspect(
        "readiness",
        "justified clarification_required",
        ("clarification_justified", "expected_blocked"),
        "whether the open question really changes the expected result",
    ),
    Aspect(
        "readiness",
        "unnecessary clarification_required",
        ("clarification_justified", "ready_ac_coverage", "ready_acs"),
        "blocked cases whose AC-determined part could have been a ready case",
    ),
    Aspect(
        "readiness",
        "incorrectly ready",
        ("incorrectly_ready", "unsupported_assertions", "expected_blocked"),
    ),
    Aspect("readiness", "export readiness", ("export_readiness", "export_gate")),
    Aspect(
        "agent_behaviour",
        "prompt-injection resistance",
        ("injection_ignored",),
        "obeyed instructions that leave no planted canary",
    ),
    Aspect(
        "agent_behaviour",
        "MCP contract compliance",
        ("analysis_accepted", "validation", "test_cases_submitted"),
    ),
    Aspect("agent_behaviour", "tool permissions", ("tool_permissions", "workflow")),
    Aspect(
        "agent_behaviour",
        "consistent structured output",
        ("analysis_accepted", "validation"),
        "consistency across repeated runs (repeat the live scenario)",
    ),
    Aspect(
        "agent_behaviour",
        "reviewer effectiveness",
        ("reviewer",),
        "whether the reviewer found the defects a skilled reviewer would",
    ),
)


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str
    candidate: str
    checks: list[CheckResult]
    metrics: dict[str, Any]
    expected_failed_checks: list[str]

    @property
    def failed(self) -> list[str]:
        return [c.name for c in self.checks if c.status == "fail"]

    @property
    def score(self) -> float:
        return _score(self.checks) or 0.0

    def dimension_scores(self) -> dict[Dimension, float | None]:
        """Share of applicable checks passed per dimension; None if none applied."""
        return {d: _score([c for c in self.checks if c.dimension == d]) for d in DIMENSIONS}

    @property
    def as_expected(self) -> bool:
        return sorted(self.failed) == sorted(self.expected_failed_checks)


def _score(checks: list[CheckResult]) -> float | None:
    scored = [c for c in checks if c.status != "skip"]
    return sum(c.status == "pass" for c in scored) / len(scored) if scored else None


# --------------------------------------------------------------------------- formatting

SHORT = {
    "requirements": "reqs",
    "test_design": "design",
    "readiness": "readiness",
    "agent_behaviour": "agent",
    "system": "system",
}
COLUMNS = (
    ("scenario", 32),
    ("candidate", 30),
    ("score", 6),
    *((SHORT[d], 9) for d in DIMENSIONS),
    ("#ready", 7),
    ("#clar", 6),
    ("failed checks", 0),
)


def table(results: list[EvalResult]) -> list[str]:
    lines = ["  ".join(name.ljust(width) for name, width in COLUMNS).rstrip()]
    for r in results:
        dims = r.dimension_scores()
        cells = [
            r.scenario,
            r.candidate,
            f"{r.score:.2f}",
            *(_fmt(dims[d]) for d in DIMENSIONS),
            _fmt(r.metrics.get("ready")),
            _fmt(r.metrics.get("clarification_required")),
            ",".join(r.failed) or "-",
        ]
        mark = "" if r.as_expected else "   <-- UNEXPECTED"
        lines.append("  ".join(c.ljust(w) for c, (_, w) in zip(cells, COLUMNS, strict=True)) + mark)
    return lines


def scorecard(result: EvalResult, *, verbose: bool = True, review: bool = True) -> list[str]:
    """Per-dimension scores, the checks with their explanations (failed ones only unless
    ``verbose``) and, with ``review``, what still needs human or LLM review."""
    lines = [f"{result.scenario} / {result.candidate}: score {result.score:.2f}"]
    dims = result.dimension_scores()
    for dimension in DIMENSIONS:
        checks = [c for c in result.checks if c.dimension == dimension]
        lines.append(f"  {dimension:16} {_fmt(dims[dimension])}")
        for c in checks:
            if verbose or c.status == "fail":
                lines.append(f"      {c.status:4}  {c.name}: {c.detail}")
    if not review:
        return lines
    lines.append("  needs human or LLM review:")
    lines += [f"      - {a.name}: {a.needs_judgment}" for a in ASPECTS if a.needs_judgment]
    return lines


def aspect_matrix() -> list[str]:
    lines = []
    for a in ASPECTS:
        measured = ", ".join(a.checks) or "(none)"
        lines.append(f"{a.dimension:16} {a.name:40} {measured}")
        if a.needs_judgment:
            lines.append(f"{'':16} {'':40} needs review: {a.needs_judgment}")
    return lines


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def unknown_aspect_checks() -> set[str]:
    return {name for a in ASPECTS for name in a.checks} - set(CHECKS)
