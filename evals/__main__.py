"""Run the evals and print scorecards.

    uv run python -m evals                       # every scenario, all recorded candidates
    uv run python -m evals --scenario prompt_injection -v
    uv run python -m evals --run-id <RUN_ID>     # any QA Assistant run: universal checks
    uv run python -m evals --scenario <ID> --run-id <RUN_ID>   # + the scenario's reference
    uv run python -m evals --live --scenario <ID>   # run the real agents (costs tokens)
    uv run python -m evals --scorecards          # latest live scorecard per scenario
    uv run python -m evals --list                # scenarios and the checks they support
    uv run python -m evals --dimensions          # quality aspects: measured vs needs review
    uv run python -m evals --json results.json   # machine-readable results

Exit status is 1 when a recorded candidate does not fail exactly its expected checks, or
when a scored real (or live) run fails any check.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.checks import CHECKS, UNIVERSAL_CHECKS
from evals.harness import evaluate_candidate, evaluate_stored_run
from evals.live import LIVE_ROOT, run_live
from evals.report import EvalResult, aspect_matrix, scorecard, table
from evals.scenario import load_candidates, load_scenarios


def _print(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", help="Only this scenario id")
    parser.add_argument("--run-id", help="Score a real run from --output-dir")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--json", type=Path, help="Also write results as JSON to this path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show every check")
    parser.add_argument("--live", action="store_true", help="Run /qa-story headless and score it")
    parser.add_argument("--model", help="Model for --live (default: your Claude Code default)")
    parser.add_argument(
        "--scorecards", action="store_true", help=f"Show the latest scorecards in {LIVE_ROOT}"
    )
    parser.add_argument("--list", action="store_true", help="List scenarios and their checks")
    parser.add_argument(
        "--dimensions", action="store_true", help="Show what each quality aspect measures"
    )
    args = parser.parse_args(argv)

    if args.dimensions:
        for line in aspect_matrix():
            _print(line)
        return 0
    scenarios = [s for s in load_scenarios() if args.scenario in (None, s.id)]
    if not scenarios:
        parser.error(f"unknown scenario {args.scenario!r}")
    if args.list:
        _print("universal checks (every story): " + ", ".join(UNIVERSAL_CHECKS))
        for s in scenarios:
            _print(f"{s.id:32} [{s.domain}] reference checks: {', '.join(s.checks) or '-'}")
        return 0
    if args.live and len(scenarios) != 1:
        parser.error("--live needs --scenario")

    single = bool(args.run_id or args.live)
    if args.scorecards:
        results = _latest_scorecards({s.id for s in scenarios})
    elif args.live:
        results = [run_live(scenarios[0], model=args.model)]
    elif args.run_id:
        scenario = scenarios[0] if args.scenario else None
        results = [evaluate_stored_run(scenario, args.output_dir, args.run_id)]
    else:
        results = [
            evaluate_candidate(scenario, candidate)
            for scenario in scenarios
            for candidate in load_candidates(scenario.id)
        ]

    if single:
        for line in scorecard(results[0], verbose=True):
            _print(line)
    else:
        for line in table(results):
            _print(line)
        if args.verbose:
            for result in results:
                _print("")
                for line in scorecard(result, review=False):
                    _print(line)

    unexpected = [r for r in results if not r.as_expected]
    if single or args.scorecards:
        _print("\n(real runs: every check must pass)")
    else:
        _print(
            f"\n{len(results) - len(unexpected)}/{len(results)} candidates behaved as expected "
            "(reference candidates pass every check; negative controls fail exactly their "
            "expected checks)."
        )
    if args.json:
        args.json.write_text("[" + ",\n".join(_json(r) for r in results) + "]\n", encoding="utf-8")
    return 1 if unexpected else 0


def _json(result: EvalResult) -> str:
    data = result.model_dump(mode="json")
    data.update(score=result.score, dimension_scores=result.dimension_scores())
    data["failed"] = result.failed
    return json.dumps(data, sort_keys=True)


def _latest_scorecards(scenario_ids: set[str]) -> list[EvalResult]:
    latest: dict[str, Path] = {}
    for path in sorted(LIVE_ROOT.glob("*/scorecard.json")):  # names sort by timestamp
        scenario = path.parent.name.rsplit("-", 1)[0]
        if scenario in scenario_ids:
            latest[scenario] = path
    return [_load_scorecard(p) for _, p in sorted(latest.items())]


def _load_scorecard(path: Path) -> EvalResult:
    """Scorecards written before checks carried a dimension are upgraded on read."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data.get("checks", []):
        legacy = {"required_findings": "expected_findings"}
        item["name"] = legacy.get(item["name"], item["name"])
        item.setdefault("dimension", CHECKS.get(item["name"], "agent_behaviour"))
    return EvalResult.model_validate(data)


if __name__ == "__main__":
    sys.exit(main())
