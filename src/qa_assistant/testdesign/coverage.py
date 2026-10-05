from __future__ import annotations

from collections.abc import Iterable, Sequence

from qa_assistant.domain.test_case import TestCase


def build_coverage(ac_ids: Iterable[str], test_cases: Sequence[TestCase]) -> dict[str, list[str]]:
    """Map each acceptance criterion id to the ids of the test cases covering it."""
    coverage: dict[str, list[str]] = {ac_id: [] for ac_id in sorted(ac_ids, key=_ac_sort_key)}
    for tc in test_cases:
        for ac_id in tc.covers:
            if ac_id in coverage:
                coverage[ac_id].append(tc.id)
    return coverage


def _ac_sort_key(ac_id: str) -> tuple[int, str]:
    _, _, number = ac_id.partition("-")
    return (int(number), ac_id) if number.isdigit() else (0, ac_id)
