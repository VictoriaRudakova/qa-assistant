from __future__ import annotations

from enum import StrEnum


class Level(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Priority(StrEnum):
    """Internal test priority. Mapped to the target Jira priority names by the CSV mapping."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Technique(StrEnum):
    """Test design technique the case was derived with."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY_VALUE = "boundary_value"
    EQUIVALENCE_PARTITIONING = "equivalence_partitioning"
    DECISION_TABLE = "decision_table"
    STATE_TRANSITION = "state_transition"
    ERROR_HANDLING = "error_handling"
    ERROR_GUESSING = "error_guessing"


NEGATIVE_TECHNIQUES = frozenset({Technique.NEGATIVE, Technique.ERROR_HANDLING})


class RiskCategory(StrEnum):
    FUNCTIONAL = "functional"
    DATA = "data"
    INTEGRATION = "integration"
    SECURITY = "security"
    PERFORMANCE = "performance"
    USABILITY = "usability"
    ACCESSIBILITY = "accessibility"
    COMPATIBILITY = "compatibility"
    REGULATORY = "regulatory"


class FindingKind(StrEnum):
    AMBIGUITY = "ambiguity"
    MISSING_REQUIREMENT = "missing_requirement"
    INCONSISTENCY = "inconsistency"
    QUESTION = "question"


class AcceptanceCriterionSource(StrEnum):
    """Where Jira holds the criterion. There is deliberately no "inferred" source: only
    acceptance criteria fetched from Jira are authoritative. Gaps the analyst finds are
    findings, never acceptance criteria."""

    FIELD = "field"
    DESCRIPTION = "description"


class Readiness(StrEnum):
    """Whether a test case's expected behaviour is known.

    ``clarification_required`` cases depend on an unanswered product question; they are
    kept for traceability but never pass export validation and are never exported.
    """

    READY = "ready"
    CLARIFICATION_REQUIRED = "clarification_required"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


_LEVEL_SCORE = {Level.LOW: 1, Level.MEDIUM: 2, Level.HIGH: 3}


def level_score(level: Level) -> int:
    return _LEVEL_SCORE[level]
