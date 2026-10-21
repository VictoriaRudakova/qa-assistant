"""Read-only Xray Cloud client: one Test by its Jira issue key.

Contract (Xray Cloud GraphQL API v2): ``getTests(jql, limit)`` finds the Test;
``Test.testType``, ``steps {action data result}``, ``gherkin`` / ``unstructured``, ``folder``
and ``jira(fields)`` carry its content; ``Test.coverableIssues(limit, start)`` lists the
issues it covers (requirements), paged with at most 100 per page.

Scope is Jira's: the key must belong to ``JIRA_PROJECT_KEY`` (checked before any request),
the JQL is wrapped by :func:`~qa_assistant.jira.scoping.scope_jql`, and the returned key is
checked again. Output is bounded: text fields, steps per call and requirements are capped,
and the caps are reported (``truncated``, ``next_step_offset``, ``requirements_truncated``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from qa_assistant.domain.xray import XrayRequirement, XrayTest, XrayTestStep, XrayTestType
from qa_assistant.errors import NotFoundError, XrayRequestError
from qa_assistant.jira.ports import JiraClient
from qa_assistant.jira.scoping import issue_in_project, scope_jql
from qa_assistant.jira.untrusted import flag_instruction_like_text
from qa_assistant.xray.cloud_http import XrayCloudHttp

MAX_FIELD_CHARS = 4_000  # per step field
MAX_DEFINITION_CHARS = 20_000
MAX_STEPS_PER_CALL = 50
MAX_STEP_CHARS_PER_CALL = 40_000  # step text per call; later steps go to the next call
REQUIREMENT_PAGE = 100  # Xray's maximum page size
MAX_REQUIREMENTS = 200

_TEST_FIELDS = '["key", "summary", "status", "labels"]'
_REQUIREMENT_FIELDS = '["key", "summary", "status", "issuetype"]'
_REQUIREMENTS = f"""
      coverableIssues(limit: $reqLimit, start: $reqStart) {{
        total
        results {{ issueId jira(fields: {_REQUIREMENT_FIELDS}) }}
      }}"""

GET_TEST_QUERY = f"""query GetTest($jql: String, $reqLimit: Int!, $reqStart: Int) {{
  getTests(jql: $jql, limit: 1) {{
    total
    results {{
      issueId
      projectId
      testType {{ name kind }}
      steps {{ id action data result callTestIssueId }}
      gherkin
      unstructured
      folder {{ path }}
      lastModified
      jira(fields: {_TEST_FIELDS}){_REQUIREMENTS}
    }}
  }}
}}"""

GET_REQUIREMENTS_QUERY = f"""query GetTestRequirements(
  $issueIds: [String], $reqLimit: Int!, $reqStart: Int
) {{
  getTests(issueIds: $issueIds, limit: 1) {{
    total
    results {{
      issueId{_REQUIREMENTS}
    }}
  }}
}}"""


# ---------------------------------------------------------------------- raw response


class _Raw(BaseModel):
    """Xray's camelCase response fields, read by alias; unknown fields are ignored."""

    model_config = ConfigDict(extra="ignore")


class _RawCoverable(_Raw):
    issue_id: str = Field(alias="issueId")
    jira: dict[str, Any]


class _RawCoverables(_Raw):
    total: int = Field(ge=0)
    results: list[_RawCoverable]


class _RawStep(_Raw):
    id: str
    action: str | None = None
    data: str | None = None
    result: str | None = None
    call_test_issue_id: str | None = Field(default=None, alias="callTestIssueId")


class _RawTestType(_Raw):
    name: str
    kind: str


class _RawFolder(_Raw):
    path: str | None = None


class _RawTest(_Raw):
    issue_id: str = Field(alias="issueId")
    project_id: str = Field(alias="projectId")
    test_type: _RawTestType = Field(alias="testType")
    steps: list[_RawStep] | None = None
    gherkin: str | None = None
    unstructured: str | None = None
    folder: _RawFolder | None = None
    last_modified: str | None = Field(default=None, alias="lastModified")
    jira: dict[str, Any]
    coverable_issues: _RawCoverables | None = Field(default=None, alias="coverableIssues")


class _RawRequirementsOnly(_Raw):
    issue_id: str = Field(alias="issueId")
    coverable_issues: _RawCoverables = Field(alias="coverableIssues")


class _RawResults[T](_Raw):
    total: int = Field(ge=0)
    results: list[T]


# ---------------------------------------------------------------------- client


class CloudXrayClient:
    """``jira`` is the configured (project-scoped) Jira: every Test is checked against it so
    that an API key of another Jira site can never return data (see :meth:`get_test`)."""

    def __init__(
        self,
        http: XrayCloudHttp,
        *,
        jira: JiraClient,
        project_key: str,
        browse_base_url: str | None = None,
    ) -> None:
        self._http = http
        self._jira = jira
        self.project_key = project_key
        self._browse = browse_base_url.rstrip("/") + "/browse/" if browse_base_url else None

    def get_test(self, issue_key: str, *, step_offset: int = 0) -> XrayTest:
        """Fail closed on tenant identity: the issue must exist in the configured Jira
        project, and Xray's numeric issue and project ids must equal Jira's. A strong
        cross-check, not a proof: ids are unique within a site, not across sites (see
        docs/features/xray-cloud-read.md)."""
        if not issue_in_project(issue_key, self.project_key):
            raise NotFoundError(
                f"{issue_key} is outside the configured Jira project {self.project_key}."
            )
        identity = self._jira.get_issue_identity(issue_key)
        data = self._http.query(
            GET_TEST_QUERY,
            {
                "jql": scope_jql(f'key = "{issue_key}"', self.project_key),
                "reqLimit": REQUIREMENT_PAGE,
                "reqStart": 0,
            },
        )
        found = _parse(_RawResults[_RawTest], data.get("getTests"))
        if not found.results:
            raise NotFoundError(
                f"{issue_key} is not an Xray Test, or is not visible to the Xray API key."
            )
        raw = found.results[0]
        key = _str(raw.jira.get("key"))
        if key != issue_key:
            raise XrayRequestError(f"Xray returned a different issue than {issue_key}.")
        if (raw.issue_id, raw.project_id) != (identity.issue_id, identity.project_id):
            raise XrayRequestError(
                f"Xray's {issue_key} does not match the configured Jira site's issue "
                "(issue id or project id differ): the Xray API key may belong to another "
                "Jira site. No Test data was returned."
            )
        coverables = raw.coverable_issues or _RawCoverables(total=0, results=[])
        requirements = self._all_requirements(raw.issue_id, coverables)
        return self._to_test(key, raw, requirements, step_offset)

    # ------------------------------------------------------------------ mapping

    def _all_requirements(
        self, issue_id: str, first: _RawCoverables
    ) -> tuple[list[_RawCoverable], int]:
        """Follow ``coverable_issues`` pages up to ``MAX_REQUIREMENTS``."""
        items, total = list(first.results), first.total
        while first.results and len(items) < min(total, MAX_REQUIREMENTS):
            data = self._http.query(
                GET_REQUIREMENTS_QUERY,
                {"issueIds": [issue_id], "reqLimit": REQUIREMENT_PAGE, "reqStart": len(items)},
            )
            page = _parse(_RawResults[_RawRequirementsOnly], data.get("getTests"))
            if not page.results or not page.results[0].coverable_issues.results:
                break
            items += page.results[0].coverable_issues.results
        return items[:MAX_REQUIREMENTS], total

    def _to_test(
        self,
        key: str,
        raw: _RawTest,
        requirements: tuple[list[_RawCoverable], int],
        step_offset: int,
    ) -> XrayTest:
        all_steps = raw.steps or []
        steps = _step_page(all_steps, step_offset)
        end = step_offset + len(steps)
        definition = raw.gherkin or raw.unstructured
        items, total = requirements
        test = XrayTest(
            key=key,
            issue_id=raw.issue_id,
            project_id=raw.project_id,
            url=self._browse + key if self._browse else None,
            summary=_str(raw.jira.get("summary")),
            status=_name(raw.jira.get("status")),
            labels=[str(label) for label in _list(raw.jira.get("labels"))],
            test_type=XrayTestType(name=raw.test_type.name, kind=raw.test_type.kind),
            folder_path=raw.folder.path if raw.folder else None,
            last_modified=raw.last_modified,
            definition=definition[:MAX_DEFINITION_CHARS] if definition else None,
            steps=steps,
            steps_total=len(all_steps),
            next_step_offset=end if end < len(all_steps) else None,
            requirements=[self._requirement(c) for c in items],
            requirements_total=total,
            requirements_truncated=len(items) < total,
        )
        sections = [
            ("summary", test.summary),
            ("definition", test.definition or ""),
            *(
                (f"step {s.index} {name}", text)
                for s in test.steps
                for name, text in (
                    ("action", s.action),
                    ("data", s.data),
                    ("expected result", s.expected_result),
                )
            ),
            *((f"requirement {r.key}", r.summary or "") for r in test.requirements),
        ]
        return test.model_copy(
            update={"untrusted_instructions": flag_instruction_like_text(sections)}
        )

    def _requirement(self, raw: _RawCoverable) -> XrayRequirement:
        key = _str(raw.jira.get("key"))
        if not key:
            raise XrayRequestError("Xray returned a requirement without a Jira key.")
        try:
            if not issue_in_project(key, self.project_key):  # another project: key only
                return XrayRequirement(issue_id=raw.issue_id, key=key, in_project=False)
            return XrayRequirement(
                issue_id=raw.issue_id,
                key=key,
                in_project=True,
                summary=_str(raw.jira.get("summary")),
                issue_type=_name(raw.jira.get("issuetype")) or None,
                status=_name(raw.jira.get("status")) or None,
            )
        except ValidationError:
            raise XrayRequestError(f"Xray returned an invalid requirement key {key!r}.") from None


def _step_page(steps: list[_RawStep], offset: int) -> list[XrayTestStep]:
    page: list[XrayTestStep] = []
    budget = MAX_STEP_CHARS_PER_CALL
    for index, raw in enumerate(steps[offset:], start=offset + 1):
        texts = [raw.action or "", raw.data or "", raw.result or ""]
        size = sum(min(len(t), MAX_FIELD_CHARS) for t in texts)
        if page and (len(page) == MAX_STEPS_PER_CALL or size > budget):
            break
        budget -= size
        action, data, result = (t[:MAX_FIELD_CHARS] for t in texts)
        page.append(
            XrayTestStep(
                index=index,
                id=raw.id,
                action=action,
                data=data,
                expected_result=result,
                called_test_issue_id=raw.call_test_issue_id,
                truncated=any(len(t) > MAX_FIELD_CHARS for t in texts),
            )
        )
    return page


def _parse[M: BaseModel](model: type[M], value: Any) -> M:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        where = ".".join(str(p) for p in exc.errors()[0]["loc"]) or "root"
        raise XrayRequestError(f"Xray returned an unexpected Test response (at {where}).") from None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _name(value: Any) -> str:
    """A Jira field that is either a plain string or an object with ``name``."""
    if isinstance(value, Mapping):
        return _str(value.get("name"))
    return _str(value)
