"""Jira story as seen by the rest of the system (deployment-agnostic)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from qa_assistant.domain.base import AcceptanceCriterionId, DomainModel, IssueKey, NonEmptyStr
from qa_assistant.domain.enums import AcceptanceCriterionSource


class AcceptanceCriterion(DomainModel):
    id: AcceptanceCriterionId
    text: NonEmptyStr
    source: AcceptanceCriterionSource


class IssueRef(DomainModel):
    key: IssueKey
    summary: str
    issue_type: str
    status: str
    relation: str = Field(description="Link type as seen from the story, e.g. 'is blocked by'")


class Comment(DomainModel):
    author: str = Field(description="Display name only; never an email address")
    created: datetime
    body: str


class JiraStorySummary(DomainModel):
    key: IssueKey
    summary: str
    issue_type: str
    status: str


class JiraStory(DomainModel):
    key: IssueKey
    url: str | None = None
    summary: NonEmptyStr
    issue_type: str
    status: str
    priority: str | None = None
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    description: str = Field(
        default="", description="Plain text, normalized from ADF (Cloud) or wiki markup (DC)"
    )
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    links: list[IssueRef] = Field(default_factory=list)
    subtasks: list[IssueRef] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)
    fetched_at: datetime


class StorySearchPage(DomainModel):
    issues: list[JiraStorySummary]
    next_page_token: str | None = None
