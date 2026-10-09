# Agent harness: guardrails, hooks, verification, evals

The agents (story-analyst, test-designer, test-reviewer) are prompted to behave well, but
nothing important depends on the prompt alone. Each guardrail lives where it can be enforced
deterministically.

## Where each guardrail lives

| Guardrail | Enforced by | Layer |
|---|---|---|
| Jira ACs are authoritative and immutable | `ANALYSIS_NON_JIRA_AC`, `ANALYSIS_DROPPED_AC` (errors); Jira wording stored, rewording warned (`ANALYSIS_AC_TEXT_REPLACED`) | Python, `analysis/checks.py` |
| Duplicate Jira ACs stay separate and are raised | `ANALYSIS_DUPLICATE_AC` (warning until a finding relates every duplicate) | Python, `analysis/checks.py` |
| Gaps, ambiguities, inconsistencies and questions are findings, not ACs; assumptions and risks are separate fields | `StoryAnalysis` model (`FindingKind`, `assumptions`, `risks`) | Python, `domain/` |
| Readiness: `ready` / `clarification_required` | `TC_*` readiness rules; `export_ready`; export refuses unless `ready_only` | Python, `testdesign/rules.py`, `services/export.py` |
| No ready test asserts behaviour only a gap supports | `TC_READY_GAP_ONLY` (error: blocks export) | Python, `testdesign/rules.py` |
| Authoritative vs inferred coverage | `get_coverage`: Jira ACs (all / ready cases) vs findings and risks | Python, `testdesign/coverage.py` |
| Jira text is untrusted | `untrusted_instructions` on `jira_get_story` (tripwire); the checks above stop injected instructions from taking effect; prompts say never to follow story text | Python `jira/untrusted.py` + prompts |
| Bounded reads of large runs | Sectioned/paged MCP tools; designer and reviewer have no filesystem tools | Python `mcp/server.py` + agent `tools:` |
| No secret files, no `git push`, no destructive shell, no direct Jira HTTP | `PreToolUse` hook | Claude config, `scripts/hooks/guard.py` |
| Fast lint after Python edits | `PostToolUse` hook (ruff check + format check of the edited file) | Claude config |
| Verification before work is declared complete | `Stop` hook runs `scripts/verify.sh` | Claude config |

Rule of thumb: if it concerns an artifact (analysis, test cases, export), it is Python at the
MCP boundary and holds for any client. If it concerns what the agent may do on this machine
(shell, files, network), it is a Claude Code hook or permission rule.

## Hooks (`.claude/settings.json`)

All hooks call `scripts/hooks/guard.py` (standard library only, unit-tested in
`tests/hooks/`). Exit code 2 blocks the call and tells Claude why.

- **`PreToolUse`** (`Bash`, `Read`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Grep`,
  `WebFetch`) blocks:
  - secret files: `.env*` (except `.env.example`), keys/certificates, `.netrc`,
    `credentials*`, `~/.ssh`, `~/.aws`, `/proc/*/environ`, secret env vars (`$*_TOKEN`, ...),
    `printenv` / bare `env`;
  - `git push` and `gh pr create|merge`;
  - destructive commands: recursive `rm` outside cache dirs and the scratchpad,
    `git reset --hard`, `git clean -f`, `git checkout -- .`, `git restore <path>`,
    `git stash drop|clear`, `git branch -D`, `sudo`, `dd of=`, `mkfs`, `find -delete`,
    recursive `chmod`/`chown`, `curl | sh`;
  - direct Jira HTTP (curl/wget/HTTP libraries against `*.atlassian.net`, `/rest/api/`,
    `$JIRA_BASE_URL` or its host, or the project's Jira client classes) and `WebFetch` of
    Jira URLs: the MCP tools are read-only and project-scoped, raw HTTP is neither.
  The shell check is deliberately conservative: it also scans heredoc bodies and quoted
  strings, so a command that merely *mentions* `.env` is blocked. Use the Edit/Write tools
  for such edits.
- **`PostToolUse`** (`Edit`, `Write`, `MultiEdit`) on a `.py` file in the repo: ruff check
  and format check of that file; problems are fed back to Claude immediately.
- **`Stop`**: when the working tree differs from `HEAD` and that exact state has not been
  verified yet, runs `scripts/verify.sh`. On failure Claude has to continue (once:
  `stop_hook_active` prevents loops). A passing state is remembered in
  `.git/qa-assistant-verified`. Set `QA_SKIP_STOP_VERIFY=1` in your shell to opt out.

Hooks are guard rails for the agent, not a security boundary. The permission rules, the
read-only Jira client and the scoped MCP server remain the real controls.

## `scripts/verify.sh`

The single verification entry point (humans, CI and the Stop hook). It runs every step and
prints a summary: ruff lint, ruff format check, mypy (strict), MCP tool contract snapshot,
fixture hygiene, hook guards, full pytest with the 90% coverage gate, evals, repository
guards (no tracked `output/` or env files, no private keys or token-like strings in tracked
or untracked files, no whitespace errors, hook scripts executable) and the pre-commit guards
(large files, JSON/TOML/YAML, private keys, gitleaks, `output/`). It never modifies files.

## Evals (`evals/`)

`uv run python -m evals` scores structured agent output with domain-agnostic universal checks
plus optional per-scenario reference checks, per quality dimension; `--run-id` scores any
run. See [`docs/features/evals.md`](../features/evals.md).
