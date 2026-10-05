"""Real (read-only) :class:`~qa_assistant.jira.ports.JiraClient` over the Jira REST API.

* Cloud: ``/rest/api/3`` (ADF rich text, token-based ``/search/jql`` pagination).
* Data Center: ``/rest/api/2`` (wiki markup, ``startAt`` pagination; the offset is passed
  around as ``next_page_token``).

Project scoping and search caps are applied by
:class:`~qa_assistant.jira.scoping.ProjectScopedJiraClient`, which wraps this client.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from qa_assistant.config.settings import JiraDeployment
from qa_assistant.domain.story import (
    Comment,
    IssueRef,
    JiraStory,
    JiraStorySummary,
    StorySearchPage,
)
from qa_assistant.errors import JiraRequestError
from qa_assistant.jira.acceptance_criteria import extract_acceptance_criteria
from qa_assistant.jira.http import JiraHttp
from qa_assistant.jira.text import adf_to_text, wiki_to_text

STORY_FIELDS = (
    "summary",
    "issuetype",
    "status",
    "priority",
    "labels",
    "components",
    "description",
    "issuelinks",
    "subtasks",
)
SUMMARY_FIELDS = ("summary", "issuetype", "status")
# Only the most recent comments are returned: older ones are rarely relevant and add noise.
MAX_COMMENTS = 20


def _utc_now() -> datetime:
    return datetime.now(UTC)


class HttpJiraClient:
    def __init__(
        self,
        http: JiraHttp,
        *,
        deployment: JiraDeployment,
        browse_base_url: str,
        acceptance_criteria_field: str | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._http = http
        self._cloud = deployment is JiraDeployment.CLOUD
        self._api = "rest/api/3" if self._cloud else "rest/api/2"
        self._browse = browse_base_url.rstrip("/") + "/browse/"
        self._ac_field = acceptance_criteria_field
        self._clock = clock

    # ------------------------------------------------------------------ JiraClient

    def get_story(self, issue_key: str, *, include_comments: bool = False) -> JiraStory:
        fields = list(STORY_FIELDS)
        if self._ac_field:
            fields.append(self._ac_field)
        if include_comments:
            fields.append("comment")
        data = self._http.get_json(
            f"{self._api}/issue/{quote(issue_key, safe='')}",
            {"fields": ",".join(fields)},
            not_found=f"Issue {issue_key} does not exist or is not visible to the Jira account.",
        )
        return self._to_story(_mapping(data), include_comments=include_comments)

    def search_stories(
        self, jql: str, *, max_results: int, next_page_token: str | None = None
    ) -> StorySearchPage:
        params: dict[str, str | int] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ",".join(SUMMARY_FIELDS),
        }
        if self._cloud:
            if next_page_token:
                params["nextPageToken"] = next_page_token
            data = _mapping(
                self._http.get_json(
                    f"{self._api}/search/jql", params, not_found="Jira search is unavailable."
                )
            )
            token = data.get("nextPageToken")
            next_token = str(token) if token and not data.get("isLast") else None
        else:
            start = _start_at(next_page_token)
            params["startAt"] = start
            data = _mapping(
                self._http.get_json(
                    f"{self._api}/search", params, not_found="Jira search is unavailable."
                )
            )
            returned = len(_list(data.get("issues")))
            total = data.get("total")
            more = returned > 0 and isinstance(total, int) and start + returned < total
            next_token = str(start + returned) if more else None

        issues = [self._to_summary(_mapping(raw)) for raw in _list(data.get("issues"))]
        return StorySearchPage(issues=issues[:max_results], next_page_token=next_token)

    # ------------------------------------------------------------------ mapping

    def _to_story(self, data: Mapping[str, Any], *, include_comments: bool) -> JiraStory:
        key = _str(data.get("key"))
        fields = _mapping(data.get("fields"))
        description = self._rich_text(fields.get("description"))
        ac_value = self._rich_text(fields.get(self._ac_field)) if self._ac_field else None
        return JiraStory(
            key=key,
            url=self._browse + key,
            summary=_str(fields.get("summary")) or "(no summary)",
            issue_type=_name(fields.get("issuetype")),
            status=_name(fields.get("status")),
            priority=_name(fields.get("priority")) or None,
            labels=[str(label) for label in _list(fields.get("labels"))],
            components=[_name(c) for c in _list(fields.get("components")) if _name(c)],
            description=description,
            acceptance_criteria=extract_acceptance_criteria(
                field_value=ac_value, description=description
            ),
            links=[ref for link in _list(fields.get("issuelinks")) if (ref := _link_ref(link))],
            subtasks=[
                _issue_ref(_mapping(s), "has subtask") for s in _list(fields.get("subtasks"))
            ],
            comments=self._comments(fields.get("comment")) if include_comments else [],
            fetched_at=self._clock(),
        )

    def _to_summary(self, data: Mapping[str, Any]) -> JiraStorySummary:
        fields = _mapping(data.get("fields"))
        return JiraStorySummary(
            key=_str(data.get("key")),
            summary=_str(fields.get("summary")),
            issue_type=_name(fields.get("issuetype")),
            status=_name(fields.get("status")),
        )

    def _comments(self, value: Any) -> list[Comment]:
        raw = _list(_mapping(value).get("comments"))[-MAX_COMMENTS:]
        comments: list[Comment] = []
        for item in raw:
            comment = _mapping(item)
            created = _datetime(comment.get("created"))
            if created is None:
                continue
            comments.append(
                Comment(
                    # Display name only: never the author's email address.
                    author=_str(_mapping(comment.get("author")).get("displayName")) or "unknown",
                    created=created,
                    body=self._rich_text(comment.get("body")),
                )
            )
        return comments

    def _rich_text(self, value: Any) -> str:
        """Plain text from a rich-text (ADF / wiki) or simple custom field value."""
        if value is None:
            return ""
        if isinstance(value, Mapping):
            if "type" in value:
                return adf_to_text(value)
            return _str(value.get("value") or value.get("name"))  # select option
        if isinstance(value, list):
            return "\n".join(f"- {text}" for v in value if (text := self._rich_text(v)))
        text = str(value)
        return text.strip() if self._cloud else wiki_to_text(text)


# ---------------------------------------------------------------------- helpers


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _name(value: Any) -> str:
    return _str(_mapping(value).get("name"))


def _datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _issue_ref(issue: Mapping[str, Any], relation: str) -> IssueRef:
    fields = _mapping(issue.get("fields"))
    return IssueRef(
        key=_str(issue.get("key")),
        summary=_str(fields.get("summary")),
        issue_type=_name(fields.get("issuetype")),
        status=_name(fields.get("status")),
        relation=relation,
    )


def _link_ref(value: Any) -> IssueRef | None:
    link = _mapping(value)
    link_type = _mapping(link.get("type"))
    if outward := link.get("outwardIssue"):
        return _issue_ref(_mapping(outward), _str(link_type.get("outward")) or "relates to")
    if inward := link.get("inwardIssue"):
        return _issue_ref(_mapping(inward), _str(link_type.get("inward")) or "relates to")
    return None


def _start_at(token: str | None) -> int:
    if not token:
        return 0
    if not token.isdigit():
        raise JiraRequestError("Invalid next_page_token for Jira Data Center (expected an offset).")
    return int(token)
