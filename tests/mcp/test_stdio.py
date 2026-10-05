"""Launches the real server over stdio, exactly as Claude Code does via .mcp.json.

Catches anything that writes to stdout (which would corrupt the protocol) and entry-point
regressions that in-process tests cannot see.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from mcp.types import CallToolResult


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_server_starts_over_stdio(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from qa_assistant.mcp.server import main; main()"],
        env={"QA_OUTPUT_DIR": str(tmp_path), "QA_LOG_LEVEL": "DEBUG"},
        cwd=str(tmp_path),  # no .env file here
    )
    async with Client(params) as client:
        assert client.server_info is not None
        assert client.server_info.name == "qa-assistant"
        tools = {t.name for t in (await client.list_tools()).tools}
        assert {"jira_get_story", "submit_test_cases", "export_xray_csv"} <= tools
        result = await client.call_tool("list_runs", {})
        assert isinstance(result, CallToolResult)
        assert not result.is_error
