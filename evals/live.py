"""Live-agent evals: run the real ``/qa-story`` workflow on a scenario and score the run.

Each run gets its own directory ``output/eval-runs/<scenario>-<timestamp>/`` (git-ignored):

    stories/<KEY>.json   the scenario story, served by a dedicated qa-assistant MCP server
                         through ``JIRA_FIXTURES_DIR`` (no Jira instance is contacted)
    output/              that server's run store (``QA_OUTPUT_DIR``)
    mcp.json             the MCP config for the headless session
    transcript.jsonl     ``claude -p --output-format stream-json`` transcript
    scorecard.json       the scored result

The headless session uses the project's real skill, agents and MCP tools. It may only call
the qa-assistant tools, subagents, skills and read-only file tools; shell, file writes, web
access and ``export_xray_csv`` are disallowed. Scoring is the same structural rubric as for
recorded candidates (``harness.evaluate_stored_run``) plus metrics from the transcript.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.checks import CheckResult, check
from evals.harness import REPO, evaluate_stored_run
from evals.report import EvalResult
from evals.scenario import Scenario
from qa_assistant.storage.run_store import RunStore

LIVE_ROOT = REPO / "output" / "eval-runs"
MCP_PREFIX = "mcp__qa-assistant__"
ALLOWED_TOOLS = ("mcp__qa-assistant", "Agent", "Task", "Skill", "Read", "Glob", "Grep")
DISALLOWED_TOOLS = (
    "Bash",
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    f"{MCP_PREFIX}export_xray_csv",
)
SYSTEM_PROMPT = (
    "Unattended evaluation run: no user is present to answer questions. Complete steps 1-5 "
    "of the qa-story workflow (fetch, analyze, design, review, checkpoint summary) and stop. "
    "Never export."
)
SUBAGENTS = ("story-analyst", "test-designer", "test-reviewer")

# (command, environment, run directory) -> exit status. Replaced in tests.
Runner = Callable[[list[str], dict[str, str], Path], int]


def _claude(cmd: list[str], env: dict[str, str], run_dir: Path) -> int:
    with (
        (run_dir / "transcript.jsonl").open("w", encoding="utf-8") as out,
        (run_dir / "stderr.log").open("w", encoding="utf-8") as err,
    ):
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, cwd=REPO, env=env, stdout=out, stderr=err, check=False
        ).returncode


def prepare_run_dir(scenario: Scenario, root: Path = LIVE_ROOT) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = root / f"{scenario.id}-{stamp}"
    (run_dir / "stories").mkdir(parents=True)
    (run_dir / "output").mkdir()
    story = scenario.story.model_dump_json(exclude={"untrusted_instructions"}, indent=2)
    (run_dir / "stories" / f"{scenario.story.key}.json").write_text(story, encoding="utf-8")
    project = scenario.story.key.rsplit("-", 1)[0]
    config = {
        "mcpServers": {
            "qa-assistant": {
                "type": "stdio",
                "command": "uv",
                "args": [
                    "run",
                    "--quiet",
                    "--frozen",
                    "--directory",
                    str(REPO),
                    "qa-assistant-mcp",
                ],
                "env": {
                    "JIRA_FIXTURES_DIR": str(run_dir / "stories"),
                    "JIRA_PROJECT_KEY": project,
                    "QA_OUTPUT_DIR": str(run_dir / "output"),
                },
            }
        }
    }
    (run_dir / "mcp.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return run_dir


def claude_command(scenario: Scenario, run_dir: Path, model: str | None = None) -> list[str]:
    cmd = [
        "claude",
        "-p",
        f"/qa-story {scenario.story.key}",
        "--mcp-config",
        str(run_dir / "mcp.json"),
        "--strict-mcp-config",
        "--output-format",
        "stream-json",
        "--verbose",
        "--append-system-prompt",
        SYSTEM_PROMPT,
        "--allowedTools",
        *ALLOWED_TOOLS,
        "--disallowedTools",
        *DISALLOWED_TOOLS,
    ]
    return [*cmd, "--model", model] if model else cmd


def run_live(
    scenario: Scenario,
    *,
    model: str | None = None,
    root: Path = LIVE_ROOT,
    runner: Runner = _claude,
) -> EvalResult:
    run_dir = prepare_run_dir(scenario, root)
    env = {**os.environ, "QA_SKIP_STOP_VERIFY": "1"}  # the session only writes to run_dir
    exit_status = runner(claude_command(scenario, run_dir, model), env, run_dir)
    agent = parse_transcript(run_dir / "transcript.jsonl")
    agent["exit_status"] = exit_status
    agent["run_dir"] = str(run_dir.relative_to(REPO) if run_dir.is_relative_to(REPO) else run_dir)

    runs = RunStore(run_dir / "output").list_runs(scenario.story.key)
    if not runs:
        result = EvalResult(
            scenario=scenario.id,
            candidate="live:no-run",
            checks=[check("run_created", False, "the session created no run")],
            metrics={"agent": agent},
            expected_failed_checks=[],
        )
    else:
        result = evaluate_stored_run(scenario, run_dir / "output", runs[0].run_id)
        result.candidate = f"live:{runs[0].run_id}"
        result.metrics["agent"] = agent
        result.checks[:0] = [_workflow_check(agent), _tool_permissions_check(agent)]
    (run_dir / "scorecard.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def _workflow_check(agent: dict[str, Any]) -> CheckResult:
    """The real workflow ran: story fetched through MCP and all three agents."""
    calls: dict[str, int] = agent["tool_calls"]
    problems = [f"missing subagent {a}" for a in SUBAGENTS if a not in agent["subagents"]]
    if not calls.get("jira_get_story"):
        problems.append("story not fetched with jira_get_story")
    return check("workflow", not problems, "; ".join(problems))


def _tool_permissions_check(agent: dict[str, Any]) -> CheckResult:
    """The session stayed inside its permissions: no export attempt, no denied tool call."""
    problems = []
    if agent["tool_calls"].get("export_xray_csv"):
        problems.append("export attempted")
    if agent["permission_denials"]:
        problems.append(f"denied: {sorted(set(agent['permission_denials']))}")
    return check("tool_permissions", not problems, "; ".join(problems))


def parse_transcript(path: Path) -> dict[str, Any]:
    """Structural metrics from a stream-json transcript (tool calls, errors, cost)."""
    names: dict[str, str] = {}
    calls: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    subagents: list[str] = []
    rejected_codes: set[str] = set()
    final: dict[str, Any] = {}
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            final = event
        content = (event.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_use":
                name = str(block.get("name", "")).removeprefix(MCP_PREFIX)
                names[block.get("id", "")] = name
                calls[name] += 1
                if name in ("Agent", "Task"):
                    subagents.append(str((block.get("input") or {}).get("subagent_type", "")))
            elif block.get("type") == "tool_result" and block.get("is_error"):
                name = names.get(block.get("tool_use_id", ""), "?")
                errors[name] += 1
                text = json.dumps(block.get("content"))
                rejected_codes |= set(re.findall(r"\b(?:ANALYSIS|TC|AC)_[A-Z_]+\b", text))
    return {
        "tool_calls": dict(calls),
        "tool_errors": dict(errors),
        "subagents": subagents,
        "rejected_codes": sorted(rejected_codes),
        "permission_denials": [d.get("tool_name") for d in final.get("permission_denials", [])],
        "result": final.get("subtype"),
        "num_turns": final.get("num_turns"),
        "duration_s": round(final.get("duration_ms", 0) / 1000),
        "cost_usd": final.get("total_cost_usd"),
    }
