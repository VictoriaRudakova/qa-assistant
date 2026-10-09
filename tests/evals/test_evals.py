"""The eval harness itself: every recorded candidate behaves as declared, the universal checks
are domain-agnostic, and real runs can be scored without touching ``output/``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from evals.__main__ import main
from evals.checks import CHECKS, UNIVERSAL_CHECKS, unjustified_blocked
from evals.harness import PAGE_BUDGET, evaluate_candidate, evaluate_stored_run
from evals.live import SUBAGENTS, Runner, run_live
from evals.report import ASPECTS, EvalResult, unknown_aspect_checks
from evals.scenario import SCENARIOS_DIR, Candidate, Scenario, load_candidates, load_scenarios
from qa_assistant.domain.analysis import Finding, StoryAnalysis
from qa_assistant.domain.enums import FindingKind
from qa_assistant.domain.test_case import TestCase, TestCaseDraft
from qa_assistant.jira.fixtures import FixtureJiraClient
from qa_assistant.services.runs import RunService
from qa_assistant.storage.run_store import RunStore

SCENARIOS = {s.id: s for s in load_scenarios()}
CANDIDATES = [(s, c) for s in SCENARIOS.values() for c in load_candidates(s.id)]
REQUIRED_SCENARIOS = {
    "shopping_cart_normal",
    "promotion_cloning_cross_domain",
    "tiered_promotion_configuration",
    "tierless_promotion",
    "crm_campaign_personalisation",
    "api_authorisation_and_validation",
    "conflicting_acceptance_criteria",
    "duplicated_acceptance_criteria",
    "missing_requirements",
    "prompt_injection",
    "large_complex_story",
}


def reference(scenario_id: str) -> Candidate:
    return next(c for c in load_candidates(scenario_id) if c.name == "reference")


def test_required_scenarios_exist_with_reference_and_negative_control() -> None:
    assert set(SCENARIOS) >= REQUIRED_SCENARIOS
    for scenario_id in SCENARIOS:
        candidates = load_candidates(scenario_id)
        assert any(c.name == "reference" and not c.expected_failed_checks for c in candidates)
        assert any(c.expected_failed_checks for c in candidates), scenario_id


@pytest.mark.parametrize(
    ("scenario", "candidate"), CANDIDATES, ids=[f"{s.id}/{c.name}" for s, c in CANDIDATES]
)
def test_candidate_fails_exactly_its_expected_checks(
    scenario: Scenario, candidate: Candidate
) -> None:
    result = evaluate_candidate(scenario, candidate)
    assert sorted(result.failed) == sorted(candidate.expected_failed_checks), [
        c for c in result.checks if c.status == "fail"
    ]
    assert set(candidate.expected_failed_checks) <= set(CHECKS)
    if not candidate.expected_failed_checks:
        assert result.score == 1.0


# --------------------------------------------------------------------------- domain-agnostic


def test_engine_has_no_domain_knowledge() -> None:
    """The engine never names a scenario, a domain word or a project key; scenarios do."""
    engine = "".join(
        (SCENARIOS_DIR.parent / name).read_text(encoding="utf-8")
        for name in ("checks.py", "harness.py", "report.py", "scenario.py", "live.py")
    ).casefold()
    words = {"cart", "coupon", "promotion", "campaign", "bonus", "tier", "shipping", "demo-"}
    words |= {s.casefold() for s in SCENARIOS}
    assert not {w for w in words if w in engine}


def test_no_count_or_ratio_expectations_remain() -> None:
    for scenario in SCENARIOS.values():
        raw = json.loads((SCENARIOS_DIR / scenario.id / "scenario.json").read_text("utf-8"))
        assert "expectations" not in raw
        assert not any("max_" in k or "min_" in k for k in raw["reference"])


def test_scenario_must_declare_exactly_the_reference_checks_it_has_data_for() -> None:
    raw = json.loads((SCENARIOS_DIR / "tierless_promotion" / "scenario.json").read_text("utf-8"))
    undeclared = {**raw, "checks": ["ready_acs"]}
    with pytest.raises(ValidationError, match="do not match reference data"):
        Scenario.model_validate(undeclared)
    unknown_ac = json.loads(json.dumps(raw))
    unknown_ac["reference"]["ready_acs"] = ["AC-99"]
    with pytest.raises(ValidationError, match="AC-99"):
        Scenario.model_validate(unknown_ac)


def _case(case_id: str, covers: list[str], questions: list[str]) -> TestCase:
    return TestCase.model_validate(
        {
            "id": case_id,
            "title": f"Case {case_id}",
            "objective": "Synthetic",
            "steps": [{"action": "Do it", "expected_result": "It is done"}],
            "priority": "medium",
            "technique": "positive",
            "status": "clarification_required" if questions else "ready",
            "covers": covers,
            "finding_ids": questions,
            "open_question_ids": questions,
        }
    )


def test_unjustified_blocked_explains_each_case() -> None:
    findings = {
        "F-1": Finding(id="F-1", kind=FindingKind.AMBIGUITY, text="x", related_ac_ids=["AC-1"]),
        "F-2": Finding(id="F-2", kind=FindingKind.QUESTION, text="y", related_ac_ids=[]),
    }
    cases = [
        _case("TC-001", ["AC-1"], []),  # ready: never judged here
        _case("TC-002", ["AC-1"], ["F-1"]),  # justified
        _case("TC-003", ["AC-1"], ["F-1"]),  # same question, same AC
        _case("TC-004", ["AC-2"], ["F-1"]),  # question is about another AC
        _case("TC-005", [], ["F-2"]),  # verifies no AC
        _case("TC-006", ["AC-1"], ["F-9"]),  # unknown question
    ]
    reasons = unjustified_blocked(cases, findings)
    assert set(reasons) == {"TC-003", "TC-004", "TC-005", "TC-006"}
    assert "repeats TC-002" in reasons["TC-003"]
    assert "relate to none" in reasons["TC-004"]
    assert reasons["TC-005"] == "verifies no Jira AC"
    assert reasons["TC-006"] == "names no known open question"


def test_quality_aspects_name_only_real_checks_and_list_what_needs_review() -> None:
    assert not unknown_aspect_checks()
    assert any(a.needs_judgment for a in ASPECTS)
    assert all(a.checks or a.needs_judgment for a in ASPECTS)
    assert "clarification_justified" in UNIVERSAL_CHECKS
    assert "expected_blocked" not in UNIVERSAL_CHECKS


def test_dimension_scores_ignore_skipped_checks() -> None:
    scenario = SCENARIOS["shopping_cart_normal"]
    result = evaluate_candidate(scenario, reference(scenario.id))
    scores = result.dimension_scores()
    assert set(scores) == {"requirements", "test_design", "readiness", "agent_behaviour", "system"}
    assert all(score == 1.0 for score in scores.values())
    assert any(c.status == "skip" for c in result.checks)  # e.g. duplicate_acs_raised


# --------------------------------------------------------------------------- scoring runs


def test_large_story_is_read_in_bounded_pages() -> None:
    result = evaluate_candidate(SCENARIOS["large_complex_story"], reference("large_complex_story"))
    assert result.metrics["test_cases"] == 120
    assert result.metrics["page_calls"] > 2
    assert result.metrics["max_page_bytes"] <= PAGE_BUDGET


def test_reviewer_metrics() -> None:
    result = evaluate_candidate(
        SCENARIOS["missing_requirements"], reference("missing_requirements")
    )
    reviewer = result.metrics["reviewer"]
    assert reviewer["errors_before"] == 1
    assert reviewer["errors_after"] == 0
    assert (reviewer["cases_added"], reviewer["cases_removed"]) == (1, 0)
    assert reviewer["cases_changed"] == 1
    assert reviewer["lost_ready_ac_coverage"] == []


def _stored_run(tmp_path: Path, scenario_id: str) -> tuple[Path, str]:
    candidate = reference(scenario_id)
    output = tmp_path / "output"
    runs = RunService(RunStore(output))  # as after a /qa-story run without Jira
    run_id = runs.submit_story_analysis(StoryAnalysis.model_validate(candidate.analysis)).run_id
    runs.submit_test_cases(run_id, [TestCaseDraft.model_validate(d) for d in candidate.test_cases])
    return output, run_id


def test_stored_run_is_scored_on_a_copy(tmp_path: Path) -> None:
    scenario = SCENARIOS["conflicting_acceptance_criteria"]
    output, run_id = _stored_run(tmp_path, scenario.id)
    before = sorted(p.relative_to(output) for p in output.rglob("*"))

    result = evaluate_stored_run(scenario, output, run_id)
    assert result.failed == []
    assert result.candidate == f"run:{run_id}"
    assert sorted(p.relative_to(output) for p in output.rglob("*")) == before


def test_any_run_is_scored_with_universal_checks_only(tmp_path: Path) -> None:
    output, run_id = _stored_run(tmp_path, "api_authorisation_and_validation")
    result = evaluate_stored_run(None, output, run_id)
    assert result.scenario == "-"
    assert result.failed == []
    names = {c.name for c in result.checks}
    assert names <= set(UNIVERSAL_CHECKS)
    skipped = {c.name: c.detail for c in result.checks if c.status == "skip"}
    assert "no independent Jira snapshot" in skipped["ac_preserved"]


def test_cli_writes_json_and_reports_success(tmp_path: Path) -> None:
    out = tmp_path / "results.json"
    assert main(["--scenario", "prompt_injection", "--json", str(out), "-v"]) == 0
    results = json.loads(out.read_text(encoding="utf-8"))
    assert {r["candidate"] for r in results} == {"reference", "obeyed_injection"}
    assert all({"dimension_scores", "score", "failed"} <= set(r) for r in results)


def test_cli_scores_a_run_without_a_scenario(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output, run_id = _stored_run(tmp_path, "tierless_promotion")
    assert main(["--run-id", run_id, "--output-dir", str(output)]) == 0
    out = capsys.readouterr().out
    assert "needs human or LLM review" in out
    assert "readiness" in out


def test_cli_lists_scenarios_and_dimensions(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list"]) == 0
    listed = capsys.readouterr().out
    assert "universal checks" in listed
    assert all(s in listed for s in REQUIRED_SCENARIOS)
    assert main(["--dimensions"]) == 0
    assert "needs review" in capsys.readouterr().out


def test_cli_rejects_bad_arguments() -> None:
    with pytest.raises(SystemExit):
        main(["--scenario", "nope"])
    with pytest.raises(SystemExit):
        main(["--live"])


# --------------------------------------------------------------------------- live mode


def write_transcript(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n", encoding="utf-8")


def tool_use(tool_id: str, name: str, **tool_input: Any) -> dict[str, Any]:
    block = {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}
    return {"type": "assistant", "message": {"content": [block]}}


def tool_error(tool_id: str, text: str) -> dict[str, Any]:
    block = {"type": "tool_result", "tool_use_id": tool_id, "is_error": True, "content": text}
    return {"type": "user", "message": {"content": [block]}}


def fake_session(candidate: Candidate, *, denials: tuple[str, ...] = ()) -> Runner:
    """Stands in for `claude -p`: drives the run through the fixture-backed services the way
    the agents would, and writes a transcript."""

    def run(cmd: list[str], env: dict[str, str], run_dir: Path) -> int:
        assert cmd[:3] == ["claude", "-p", "/qa-story DEMO-205"]
        assert "Bash" in cmd[cmd.index("--disallowedTools") :]
        assert env["QA_SKIP_STOP_VERIFY"] == "1"
        config = json.loads((run_dir / "mcp.json").read_text(encoding="utf-8"))
        server_env = config["mcpServers"]["qa-assistant"]["env"]
        jira = FixtureJiraClient(Path(server_env["JIRA_FIXTURES_DIR"]))
        runs = RunService(RunStore(Path(server_env["QA_OUTPUT_DIR"])), jira)
        assert jira.get_story("DEMO-205").untrusted_instructions
        run_id = runs.submit_story_analysis(StoryAnalysis.model_validate(candidate.analysis)).run_id
        drafts = [TestCaseDraft.model_validate(d) for d in candidate.test_cases]
        runs.submit_test_cases(run_id, drafts)
        runs.submit_test_cases(run_id, drafts)  # reviewer: no changes needed
        events = [
            tool_use("1", "mcp__qa-assistant__jira_get_story", issue_key="DEMO-205"),
            *(tool_use(str(n), "Agent", subagent_type=a) for n, a in enumerate(SUBAGENTS, 2)),
            tool_use("9", "mcp__qa-assistant__submit_story_analysis"),
            tool_error("9", "[invalid_artifact] ANALYSIS_NON_JIRA_AC: AC-4 is not in Jira."),
            {
                "type": "result",
                "subtype": "success",
                "num_turns": 12,
                "duration_ms": 61_000,
                "total_cost_usd": 1.5,
                "permission_denials": [{"tool_name": d} for d in denials],
            },
        ]
        write_transcript(run_dir / "transcript.jsonl", events)
        return 0

    return run


def test_live_run_is_scored_with_agent_metrics(tmp_path: Path) -> None:
    scenario = SCENARIOS["prompt_injection"]
    result = run_live(scenario, root=tmp_path, runner=fake_session(reference(scenario.id)))

    assert result.candidate.startswith("live:")
    assert result.failed == []
    agent = result.metrics["agent"]
    assert agent["subagents"] == list(SUBAGENTS)
    assert agent["tool_errors"] == {"submit_story_analysis": 1}
    assert agent["rejected_codes"] == ["ANALYSIS_NON_JIRA_AC"]
    assert (agent["cost_usd"], agent["duration_s"]) == (1.5, 61)
    assert result.metrics["reviewer"]["revisions"] == 2
    run_dir = next(tmp_path.iterdir())
    saved = EvalResult.model_validate_json((run_dir / "scorecard.json").read_text("utf-8"))
    assert saved.candidate == result.candidate


def test_live_run_with_a_denied_tool_fails_tool_permissions(tmp_path: Path) -> None:
    scenario = SCENARIOS["prompt_injection"]
    runner = fake_session(reference(scenario.id), denials=("Bash",))
    result = run_live(scenario, root=tmp_path, runner=runner)
    assert result.failed == ["tool_permissions"]
    assert result.metrics["agent"]["permission_denials"] == ["Bash"]


def test_live_run_without_a_run_or_workflow_fails(tmp_path: Path) -> None:
    scenario = SCENARIOS["shopping_cart_normal"]
    result = run_live(scenario, root=tmp_path, runner=lambda cmd, env, run_dir: 1)
    assert result.failed == ["run_created"]
    assert result.metrics["agent"]["exit_status"] == 1

    def analysis_only(cmd: list[str], env: dict[str, str], run_dir: Path) -> int:
        out = Path(
            json.loads((run_dir / "mcp.json").read_text("utf-8"))["mcpServers"]["qa-assistant"][
                "env"
            ]["QA_OUTPUT_DIR"]
        )
        RunService(RunStore(out)).submit_story_analysis(
            StoryAnalysis.model_validate(reference(scenario.id).analysis)
        )
        write_transcript(
            run_dir / "transcript.jsonl", [tool_use("1", "mcp__qa-assistant__export_xray_csv")]
        )
        return 0

    result = run_live(scenario, root=tmp_path, runner=analysis_only, model="sonnet")
    assert set(result.failed) == {"workflow", "tool_permissions", "test_cases_submitted"}
    checks = {c.name: c.detail for c in result.checks}
    assert "export attempted" in checks["tool_permissions"]
    assert "jira_get_story" in checks["workflow"]


def test_cli_scorecards_and_live_argument_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.__main__ as cli

    scenario = SCENARIOS["prompt_injection"]
    monkeypatch.setattr(cli, "LIVE_ROOT", tmp_path)
    monkeypatch.setattr(
        cli,
        "run_live",
        lambda s, model=None: run_live(
            s, root=tmp_path, runner=fake_session(reference(scenario.id))
        ),
    )
    assert main(["--live", "--scenario", "prompt_injection"]) == 0
    assert main(["--scorecards"]) == 0


def test_legacy_scorecards_are_upgraded_on_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.__main__ as cli

    legacy = {
        "scenario": "prompt_injection",
        "candidate": "live:old",
        "checks": [
            {"name": "required_findings", "status": "pass", "detail": ""},
            {"name": "clarification_required", "status": "fail", "detail": "6 (expected 0..2)"},
        ],
        "metrics": {},
        "expected_failed_checks": [],
    }
    run_dir = tmp_path / "prompt_injection-20260101T000000000000Z"
    run_dir.mkdir()
    (run_dir / "scorecard.json").write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setattr(cli, "LIVE_ROOT", tmp_path)
    assert main(["--scorecards", "--scenario", "prompt_injection"]) == 1
