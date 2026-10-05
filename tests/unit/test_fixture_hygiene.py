"""Guards that test fixtures stay synthetic.

Fixtures must never contain real company data: only the DEMO project, example.com
addresses/hosts and no token-like strings. If this fails, anonymize the fixture.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.support import FIXTURES

FIXTURE_FILES = sorted(p for p in FIXTURES.rglob("*") if p.is_file())

EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
URL_HOST_RE = re.compile(r"https?://([^/\s\"']+)")
ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]+)-\d+\b")
TOKEN_RES = [
    re.compile(r"ATATT[A-Za-z0-9_\-=]{10,}"),  # Atlassian API token prefix
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9+/=._-]{16,}"),
    re.compile(r"\b(ghp|gho|github_pat|sk-ant|xox[abp])[_-][A-Za-z0-9_-]{10,}"),
]
ALLOWED_DOMAINS = re.compile(r"(^|\.)example\.(com|org|net)$")
ALLOWED_PROJECTS = {"DEMO", "OTHER", "AC", "TC"}


def test_fixtures_exist() -> None:
    assert FIXTURE_FILES


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_fixture_is_synthetic(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for domain in EMAIL_RE.findall(text) + URL_HOST_RE.findall(text):
        assert ALLOWED_DOMAINS.search(domain), f"non-example domain {domain!r}"
    for project in ISSUE_KEY_RE.findall(text):
        assert project in ALLOWED_PROJECTS, f"unexpected Jira project {project!r}"
    for token_re in TOKEN_RES:
        assert not token_re.search(text), f"token-like value matching {token_re.pattern}"
