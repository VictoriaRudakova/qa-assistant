#!/usr/bin/env bash
# Single deterministic verification entry point for humans, CI and the Claude Code Stop hook.
#
#   scripts/verify.sh            run every step, then print a summary (exit 1 if any failed)
#
# Steps: ruff lint, ruff format check, mypy (strict), MCP tool contract, fixture hygiene,
# hook guards, full pytest with the coverage gate, evals, repository guards (tracked and
# untracked files) and the pre-commit guards (large files, private keys, gitleaks, output/).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

failures=()
step() {
  local name=$1
  shift
  printf '\n==> %s\n' "$name"
  if ! "$@"; then
    failures+=("$name")
  fi
}

repository_guards() {
  local bad=0
  # Generated artifacts may contain Jira data; secrets files must never be tracked.
  if git ls-files output | grep -v '^output/\.gitkeep$'; then
    echo "error: files under output/ are tracked"
    bad=1
  fi
  if git ls-files | grep -E '(^|/)\.env(\..+)?$' | grep -vE '\.env\.(example|sample|template)$'; then
    echo "error: an env file is tracked"
    bad=1
  fi
  # Tracked AND untracked (not ignored) files, so new files are checked before `git add`.
  # Patterns are split so this script does not match itself.
  local key_re='-----BEGIN ([A-Z]+ )?PRIVATE'' KEY-----'
  local token_re='ATA''TT[A-Za-z0-9_=-]{10,}|(ghp|github_pat|sk-ant|xox[abp])[_-][A-Za-z0-9_-]{16,}'
  local status=0
  git grep --untracked -nIE -e "$key_re" -e "$token_re" -- . ':!uv.lock' || status=$?
  if ((status == 0)); then
    echo "error: private key or token-like value found"
    bad=1
  elif ((status != 1)); then
    echo "error: git grep failed (exit $status)"
    bad=1
  fi
  if ! git diff --check HEAD; then
    echo "error: whitespace errors in changed lines"
    bad=1
  fi
  # Every hook command in .claude/settings.json must point at an executable script.
  local script
  for script in $(grep -oE 'scripts/[A-Za-z0-9_./-]+' .claude/settings.json | sort -u); do
    if [[ ! -x "$script" ]]; then
      echo "error: hook script $script is missing or not executable"
      bad=1
    fi
  done
  return "$bad"
}

step "ruff lint" uv run --frozen ruff check .
step "ruff format" uv run --frozen ruff format --check .
step "mypy (strict)" uv run --frozen mypy
step "MCP tool contract" uv run --frozen pytest -q --no-header tests/mcp
step "fixture hygiene" uv run --frozen pytest -q --no-header tests/unit/test_fixture_hygiene.py
step "hook guards" uv run --frozen pytest -q --no-header tests/hooks
step "pytest + coverage gate" uv run --frozen pytest -q --no-header --cov
step "evals" uv run --frozen python -m evals
step "repository guards" repository_guards
# The whitespace fixers are skipped (verification must not modify files); the
# `git diff --check` repository guard covers them read-only.
step "pre-commit guards" env SKIP=ruff-check,ruff-format,mypy,end-of-file-fixer,trailing-whitespace \
  uv run --frozen pre-commit run --all-files --show-diff-on-failure

printf '\n'
if ((${#failures[@]})); then
  printf 'verify: FAILED (%s)\n' "$(IFS=,; echo "${failures[*]}")"
  exit 1
fi
echo "verify: all checks passed"
