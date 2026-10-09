"""MCP server tests using the SDK's in-process client.

The tool-schema snapshot pins the public MCP contract. After an intentional change:
    UPDATE_SNAPSHOTS=1 uv run pytest tests/mcp
and review the diff.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from qa_assistant.config.settings import load_settings
from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.test_case import TestCaseDraft
from qa_assistant.jira.scoping import ProjectScopedJiraClient
from qa_assistant.mcp.server import ServerDependencies, build_dependencies, create_server
from qa_assistant.services.export import ExportService
from qa_assistant.services.runs import RunService
from qa_assistant.storage.run_store import RunStore
from qa_assistant.xray.csv_exporter import MappedXrayCsvExporter
from qa_assistant.xray.mapping import XrayCsvMapping
from tests.support import FIXTURES, FakeJiraClient, load_json

SNAPSHOT = Path(__file__).parent / "snapshots" / "tool_schemas.json"
EXPECTED_TOOLS = {
    "jira_get_story",
    "jira_search_stories",
    "submit_story_analysis",
    "submit_test_cases",
    "validate_test_cases",
    "export_xray_csv",
    "get_run",
    "get_story_analysis",
    "list_test_cases",
    "get_test_cases",
    "list_runs",
    "get_coverage",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def server(
    store: RunStore, fake_jira: FakeJiraClient, synthetic_mapping: XrayCsvMapping
) -> MCPServer:
    jira = ProjectScopedJiraClient(fake_jira, "DEMO", max_search_results=50)
    deps = ServerDependencies(
        jira=jira,
        runs=RunService(store, jira),
        export=ExportService(store, MappedXrayCsvExporter(synthetic_mapping)),
    )
    return create_server(deps)


@pytest.fixture
async def client(server: MCPServer) -> AsyncIterator[Client]:
    async with Client(server) as connected:
        yield connected


def text_of(result: CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, TextContent))


async def call_ok(client: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await client.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    assert not result.is_error, text_of(result)
    content: dict[str, Any] | None = result.structured_content
    assert content is not None
    return content


async def call_error(client: Client, name: str, arguments: dict[str, Any]) -> str:
    result = await client.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    assert result.is_error
    return text_of(result)


@pytest.mark.anyio
async def test_tool_names_and_annotations(client: Client) -> None:
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == EXPECTED_TOOLS
    read_only = {n for n, t in tools.items() if t.annotations and t.annotations.read_only_hint}
    assert read_only == {
        "jira_get_story",
        "jira_search_stories",
        "validate_test_cases",
        "get_run",
        "get_story_analysis",
        "list_test_cases",
        "get_test_cases",
        "list_runs",
        "get_coverage",
    }
    assert not any(t.annotations and t.annotations.destructive_hint for t in tools.values())


@pytest.mark.anyio
async def test_tool_schemas_match_snapshot(client: Client) -> None:
    tools = sorted((await client.list_tools()).tools, key=lambda t: t.name)
    current = {
        t.name: {
            "description": t.description,
            "inputSchema": t.input_schema,
            "outputSchema": t.output_schema,
        }
        for t in tools
    }
    rendered = json.dumps(current, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(rendered, encoding="utf-8")
    assert rendered == SNAPSHOT.read_text(encoding="utf-8"), "MCP tool contract changed"


@pytest.mark.anyio
async def test_end_to_end_story_to_csv(client: Client) -> None:
    story = await call_ok(client, "jira_get_story", {"issue_key": "DEMO-101"})
    assert [ac["id"] for ac in story["acceptance_criteria"]] == ["AC-1", "AC-2", "AC-3", "AC-4"]

    analysis = load_json("analysis/DEMO-101.analysis.json")
    submitted = await call_ok(client, "submit_story_analysis", {"analysis": analysis})
    run_id = submitted["run_id"]

    drafts = load_json("test_cases/DEMO-101.drafts.json")
    tests = await call_ok(client, "submit_test_cases", {"run_id": run_id, "test_cases": drafts})
    assert tests["report"]["valid"] is True
    assert tests["report"]["coverage"]["AC-2"] == ["TC-002", "TC-003"]

    report = await call_ok(client, "validate_test_cases", {"run_id": run_id})
    assert report["valid"] is True

    exported = await call_ok(client, "export_xray_csv", {"run_id": run_id})
    golden = (FIXTURES / "xray" / "DEMO-101.synthetic.csv").read_bytes()
    assert Path(exported["path"]).read_bytes() == golden

    runs = await client.call_tool("list_runs", {"story_key": "DEMO-101"})
    assert run_id in text_of(runs)


@pytest.mark.anyio
async def test_run_is_read_in_sections(client: Client) -> None:
    analysis = load_json("analysis/DEMO-101.analysis.json")
    run_id = (await call_ok(client, "submit_story_analysis", {"analysis": analysis}))["run_id"]

    empty = await call_ok(client, "get_run", {"run_id": run_id})
    assert (empty["revision"], empty["test_case_count"]) == (None, 0)
    assert empty["acceptance_criterion_ids"] == ["AC-1", "AC-2", "AC-3", "AC-4"]

    result = await client.call_tool("get_story_analysis", {"run_id": run_id})
    assert isinstance(result, CallToolResult)
    assert not result.is_error, text_of(result)
    stored = json.loads(text_of(result))
    assert [r["severity"] for r in stored["risks"]] == ["high", "medium"]

    drafts = load_json("test_cases/DEMO-101.drafts.json")
    await call_ok(client, "submit_test_cases", {"run_id": run_id, "test_cases": drafts})
    overview = await call_ok(client, "get_run", {"run_id": run_id})
    assert (overview["revision"], overview["test_case_count"], overview["ready_count"]) == (1, 5, 5)

    index = await call_ok(client, "list_test_cases", {"run_id": run_id, "limit": 3})
    assert [i["id"] for i in index["items"]] == ["TC-001", "TC-002", "TC-003"]
    assert index["next_offset"] == 3
    assert "steps" not in index["items"][0]

    page = await call_ok(client, "get_test_cases", {"run_id": run_id, "offset": 3})
    assert [tc["id"] for tc in page["test_cases"]] == ["TC-004", "TC-005"]
    assert page["test_cases"][0]["steps"]
    chosen = await call_ok(client, "get_test_cases", {"run_id": run_id, "ids": ["TC-002"]})
    assert [tc["id"] for tc in chosen["test_cases"]] == ["TC-002"]

    coverage = await call_ok(client, "get_coverage", {"run_id": run_id})
    assert coverage["acceptance_criteria"]["AC-2"] == ["TC-002", "TC-003"]
    assert coverage["acceptance_criteria_ready"] == coverage["acceptance_criteria"]
    assert set(coverage["findings"]) == {"F-1", "F-2"}
    assert set(coverage["risks"]) == {"R-1", "R-2"}
    assert coverage["uncovered_ac_ids"] == []
    assert "issues" not in coverage


@pytest.mark.anyio
async def test_analysis_with_invented_acceptance_criterion_is_rejected(client: Client) -> None:
    analysis = load_json("analysis/DEMO-101.analysis.json")
    analysis["acceptance_criteria"].append(
        {"id": "AC-5", "text": "Invented criterion.", "source": "description"}
    )
    message = await call_error(client, "submit_story_analysis", {"analysis": analysis})
    assert "[invalid_artifact]" in message
    assert "AC-5 is not in Jira" in message


@pytest.mark.anyio
async def test_export_blocked_while_clarification_required(client: Client) -> None:
    analysis = load_json("analysis/DEMO-101.analysis.json")
    run_id = (await call_ok(client, "submit_story_analysis", {"analysis": analysis}))["run_id"]
    drafts = load_json("test_cases/DEMO-101.drafts.json")
    drafts.append(
        {
            **drafts[2],
            "title": "Reused reset link follows the agreed rule",
            "status": "clarification_required",
            "covers": [],
            "finding_ids": ["F-1"],
            "open_question_ids": ["F-1"],
        }
    )
    submitted = await call_ok(client, "submit_test_cases", {"run_id": run_id, "test_cases": drafts})
    report = submitted["report"]
    assert (report["valid"], report["export_ready"]) == (True, False)
    assert report["clarification_required_test_case_ids"] == ["TC-006"]
    assert report["finding_coverage"]["F-1"] == ["TC-006"]

    message = await call_error(client, "export_xray_csv", {"run_id": run_id})
    assert "[export_blocked]" in message
    assert "CLARIFICATION_REQUIRED" in message
    exported = await call_ok(client, "export_xray_csv", {"run_id": run_id, "ready_only": True})
    assert exported["excluded_test_case_ids"] == ["TC-006"]
    assert exported["test_case_count"] == 5


@pytest.mark.anyio
async def test_search_is_project_scoped(client: Client, fake_jira: FakeJiraClient) -> None:
    page = await call_ok(client, "jira_search_stories", {"jql": "status = Done"})
    assert [i["key"] for i in page["issues"]] == ["DEMO-101"]
    assert fake_jira.last_jql == 'project = "DEMO" AND (status = Done)'


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "arguments", "expected"),
    [
        ("jira_get_story", {"issue_key": "OTHER-1"}, "[not_found]"),
        ("jira_get_story", {"issue_key": "DEMO-999"}, "[not_found]"),
        ("jira_get_story", {"issue_key": "not a key"}, "pattern"),
        ("validate_test_cases", {"run_id": "20261005T120000Z-ffffff"}, "[not_found]"),
        ("validate_test_cases", {"run_id": "../../etc"}, "pattern"),
        ("export_xray_csv", {"run_id": "20261005T120000Z-ffffff"}, "[not_found]"),
        ("get_run", {"run_id": "20261005T120000Z-ffffff"}, "[not_found]"),
        ("get_test_cases", {"run_id": "20261005T120000Z-ffffff"}, "[not_found]"),
        ("list_test_cases", {"run_id": "20261005T120000Z-ffffff", "limit": 101}, "100"),
        ("get_test_cases", {"run_id": "20261005T120000Z-ffffff", "limit": 26}, "25"),
    ],
)
async def test_errors_are_reported_to_the_model(
    client: Client, tool: str, arguments: dict[str, Any], expected: str
) -> None:
    assert expected in await call_error(client, tool, arguments)


@pytest.mark.anyio
async def test_llm_cannot_send_unknown_fields(client: Client) -> None:
    analysis = {**load_json("analysis/DEMO-101.analysis.json"), "xray_csv": "TCID,Summary"}
    message = await call_error(client, "submit_story_analysis", {"analysis": analysis})
    assert "xray_csv" in message


@pytest.mark.anyio
async def test_export_blocked_when_invalid(client: Client) -> None:
    analysis = load_json("analysis/DEMO-101.analysis.json")
    run_id = (await call_ok(client, "submit_story_analysis", {"analysis": analysis}))["run_id"]
    drafts = load_json("test_cases/DEMO-101.drafts.json")[:4]
    submitted = await call_ok(client, "submit_test_cases", {"run_id": run_id, "test_cases": drafts})
    assert submitted["report"]["valid"] is False
    message = await call_error(client, "export_xray_csv", {"run_id": run_id})
    assert "[export_blocked]" in message
    assert "AC_NOT_COVERED" in message


@pytest.mark.anyio
async def test_server_without_configuration_reports_not_configured(tmp_path: Path) -> None:
    settings = load_settings(env_file=None).model_copy(deep=True)
    settings.app.output_dir = tmp_path
    server = create_server(build_dependencies(settings))
    async with Client(server) as unconfigured:
        jira_error = await call_error(unconfigured, "jira_get_story", {"issue_key": "DEMO-1"})
        assert "[not_configured]" in jira_error
        assert "JIRA_BASE_URL" in jira_error

        analysis = load_json("analysis/DEMO-101.analysis.json")
        run = await call_ok(unconfigured, "submit_story_analysis", {"analysis": analysis})
        drafts = load_json("test_cases/DEMO-101.drafts.json")
        await call_ok(
            unconfigured, "submit_test_cases", {"run_id": run["run_id"], "test_cases": drafts}
        )
        export_error = await call_error(unconfigured, "export_xray_csv", {"run_id": run["run_id"]})
        assert "XRAY_CSV_MAPPING_FILE" in export_error


def test_build_dependencies_loads_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XRAY_CSV_MAPPING_FILE", str(FIXTURES / "xray" / "synthetic_mapping.json"))
    monkeypatch.setenv("QA_OUTPUT_DIR", str(tmp_path))
    deps = build_dependencies(load_settings(env_file=None))
    run_id = deps.runs.submit_story_analysis(
        StoryAnalysis.model_validate(load_json("analysis/DEMO-101.analysis.json"))
    ).run_id
    assert (tmp_path / "runs" / run_id / "analysis.json").is_file()
    deps.runs.submit_test_cases(
        run_id,
        [TestCaseDraft.model_validate(d) for d in load_json("test_cases/DEMO-101.drafts.json")],
    )
    exported = deps.export.export_xray_csv(run_id)
    assert exported.mapping_name == "synthetic-placeholder"
