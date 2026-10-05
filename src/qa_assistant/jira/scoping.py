"""Restricts every Jira read to the configured project (``JIRA_PROJECT_KEY``) and caps
search size (``JIRA_MAX_SEARCH_RESULTS``).

A deterministic guard, independent of the LLM: even if a model (or injected story text) asks
for an issue in another project, or for an unbounded search, the request never reaches Jira.
"""

from __future__ import annotations

import re

from qa_assistant.domain.story import JiraStory, StorySearchPage
from qa_assistant.errors import NotFoundError
from qa_assistant.jira.ports import JiraClient

_ORDER_BY_RE = re.compile(r"(?:^|\s+)order\s+by\s+", re.IGNORECASE)


def scope_jql(jql: str, project_key: str) -> str:
    """Wrap ``jql`` so it can only match issues in ``project_key``.

    The user query is parenthesized, so a top-level ``OR`` cannot escape the project filter.
    A trailing ``ORDER BY`` clause is kept outside the parentheses.
    """
    where, order_by = jql.strip(), ""
    matches = list(_ORDER_BY_RE.finditer(where))
    if matches:
        last = matches[-1]
        where, order_by = where[: last.start()].strip(), where[last.end() :].strip()
    condition = f'project = "{project_key}"'
    if where:
        condition += f" AND ({where})"
    return f"{condition} ORDER BY {order_by}" if order_by else condition


def issue_in_project(issue_key: str, project_key: str) -> bool:
    return issue_key.rsplit("-", 1)[0] == project_key


class ProjectScopedJiraClient:
    """Decorates a :class:`JiraClient`: one project only, bounded search results."""

    def __init__(self, inner: JiraClient, project_key: str, *, max_search_results: int) -> None:
        self._inner = inner
        self.project_key = project_key
        self.max_search_results = max_search_results

    def get_story(self, issue_key: str, *, include_comments: bool = False) -> JiraStory:
        if not issue_in_project(issue_key, self.project_key):
            raise NotFoundError(
                f"{issue_key} is outside the configured Jira project {self.project_key}."
            )
        return self._inner.get_story(issue_key, include_comments=include_comments)

    def search_stories(
        self, jql: str, *, max_results: int, next_page_token: str | None = None
    ) -> StorySearchPage:
        page = self._inner.search_stories(
            scope_jql(jql, self.project_key),
            max_results=min(max_results, self.max_search_results),
            next_page_token=next_page_token,
        )
        # Defense in depth: drop anything the backend returned from another project.
        issues = [i for i in page.issues if issue_in_project(i.key, self.project_key)]
        return page.model_copy(update={"issues": issues})
