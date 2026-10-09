#!/usr/bin/env python3
"""Claude Code hooks for this repository (configured in ``.claude/settings.json``).

    guard.py pre-tool   PreToolUse: block secret files, git push, destructive commands and
                        direct Jira HTTP access (the MCP Jira tools exist for that).
    guard.py post-edit  PostToolUse on Edit/Write: ruff lint + format check of an edited .py.
    guard.py stop       Stop: run scripts/verify.sh once per changed working tree.

Exit code 2 blocks the tool call (or the stop) and shows stderr to Claude. The decision
functions are pure so ``tests/hooks`` can test them. Standard library only, Python >= 3.10:
hooks must work before ``uv sync`` and must start fast.

These hooks are guard rails for the agent, not a security boundary: permission rules in
``.claude/settings.json`` and the read-only, project-scoped MCP server are the real controls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]

# ------------------------------------------------------------------------ secret files

SAFE_ENV_FILES = frozenset({".env.example", ".env.sample", ".env.template"})
SECRET_NAME = re.compile(
    r"^(?:\.env(?:\..+)?|.+\.(?:pem|key|p12|pfx|jks|keystore)|id_(?:rsa|dsa|ecdsa|ed25519)"
    r"|\.netrc|\.pgpass|\.pypirc|\.npmrc|credentials(?:\.json)?|secrets?\.(?:json|ya?ml|toml))$"
)
SECRET_DIRS = frozenset({".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker"})
SECRET_ENV_VAR = re.compile(r"\$\{?\w*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY)\w*")


def secret_path_reason(path: str) -> str | None:
    """Why ``path`` is a secret file, or None. Matches on the name, so relative, absolute and
    ``~`` paths are all covered."""
    parts = PurePosixPath(path.strip().strip("'\"")).parts
    if not parts:
        return None
    name = parts[-1]
    if name in SAFE_ENV_FILES or name.endswith(".pub"):
        return None
    if SECRET_NAME.match(name) or name.startswith(".env"):  # also globs such as .env*
        return f"{name} may contain secrets (use load_settings()/missing_settings())"
    if SECRET_DIRS & set(parts) or ("/proc/" in path and path.endswith("/environ")):
        return f"{path} is a credential location"
    return None


# ------------------------------------------------------------------------ shell commands

SEPARATORS = re.compile(r"&&|\|\||[;&|\n]|\$\(|`|<\(|>\(|[()]")
WRAPPERS = frozenset({"command", "exec", "nohup", "time", "nice", "timeout", "xargs", "builtin"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
SAFE_RM_DIRS = frozenset(
    {".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__", "htmlcov", "build", "dist"}
)
JIRA_TARGET = re.compile(
    r"atlassian\.net|/rest/api/|/rest/agile/|/rest/raven/|JIRA_BASE_URL|\bjira\.[\w-]+\.\w+"
    r"|HttpJiraClient|JiraHttp\b|build_jira_client",
    re.IGNORECASE,
)
NETWORK_COMMANDS = frozenset({"curl", "wget", "http", "https", "xh", "nc", "ncat", "telnet"})
INTERPRETERS = frozenset({"python", "python3", "node", "deno", "ruby", "perl", "uv", "pwsh"})
HTTP_LIBRARY = re.compile(
    r"\b(?:requests|httpx|urllib|aiohttp|fetch|Invoke-WebRequest|Invoke-RestMethod"
    r"|HttpJiraClient|JiraHttp|build_jira_client)\b"
)
JIRA_MESSAGE = (
    "direct Jira HTTP access: use the qa-assistant MCP tools "
    "(jira_get_story, jira_search_stories), which are read-only and project-scoped"
)


def _segments(command: str) -> Iterator[list[str]]:
    """Simple commands of a shell line, as argument lists (best effort, no execution)."""
    for raw in SEPARATORS.split(command):
        try:
            words = shlex.split(raw, comments=True)
        except ValueError:
            words = raw.split()
        while words and (re.match(r"^\w+=", words[0]) or words[0] in WRAPPERS):
            words = words[1:]
        if words:
            yield words


def _rm_reason(args: list[str]) -> str | None:
    flags = "".join(a.lstrip("-") for a in args if a.startswith("-") and a != "--")
    recursive = bool(re.search(r"[rR]", flags)) or "--recursive" in args
    if not recursive:
        return None
    targets = [a for a in args if not a.startswith("-")]
    for target in targets or ["?"]:
        name = PurePosixPath(target).name
        inside = not target.startswith(("/", "~", "$")) and ".." not in PurePosixPath(target).parts
        scratch = target.startswith("/tmp/claude-")  # noqa: S108 - Claude Code scratchpad
        if not ((inside and name in SAFE_RM_DIRS) or scratch):
            return f"recursive rm of {target!r} (only cache dirs and the scratchpad may be removed)"
    return None


def _git_reason(args: list[str]) -> str | None:
    # Skip global options (-C <dir>, -c key=value, --no-pager, ...) to find the subcommand.
    rest = list(args)
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in ("-C", "-c") else rest[1:]
    if not rest:
        return None
    sub, opts = rest[0], rest[1:]
    if sub == "push":
        return "git push is reserved for the user (commit/push only on explicit request)"
    destructive = {
        "reset": "--hard" in opts or "--merge" in opts or "--keep" in opts,
        "clean": any(re.match(r"^-\w*f", o) or o == "--force" for o in opts),
        "checkout": "--" in opts or "." in opts or "-f" in opts or "--force" in opts,
        "restore": "--staged" not in opts or "--worktree" in opts,
        "stash": bool(opts) and opts[0] in ("drop", "clear"),
        "branch": "-D" in opts or ("--delete" in opts and "--force" in opts),
        "filter-branch": True,
        "update-ref": "-d" in opts,
        "reflog": bool(opts) and opts[0] in ("expire", "delete"),
    }
    if destructive.get(sub):
        return f"git {sub} {' '.join(opts)} discards work; ask the user to run it"
    return None


def bash_reason(command: str, jira_host: str | None = None) -> str | None:
    """Why a Bash command must not run, or None."""
    if SECRET_ENV_VAR.search(command):
        return "command references a secret environment variable"
    if (jira_host and jira_host in command) or JIRA_TARGET.search(command):
        for words in _segments(command):
            cmd = PurePosixPath(words[0]).name
            if cmd in NETWORK_COMMANDS or (cmd in INTERPRETERS and HTTP_LIBRARY.search(command)):
                return JIRA_MESSAGE
    if re.search(r":\(\)\s*\{", command) or re.search(r">\s*/dev/(?:sd|nvme|disk)", command):
        return "destructive system command"
    if re.search(r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b", command):
        return "piping a download into a shell"
    for words in _segments(command):
        reason = _segment_reason(words, jira_host)
        if reason:
            return reason
    return None


def _segment_reason(words: list[str], jira_host: str | None) -> str | None:
    cmd, args = PurePosixPath(words[0]).name, words[1:]
    if cmd in SHELLS and "-c" in args[:-1]:
        return bash_reason(args[args.index("-c") + 1], jira_host)
    if cmd == "eval":
        return bash_reason(" ".join(args), jira_host)
    if cmd == "printenv" or (cmd == "env" and all(a.startswith("-") for a in args)):
        return "printing the environment can expose secrets"
    if cmd in ("set", "export", "declare") and args in ([], ["-p"], ["-x"]):
        return "printing the environment can expose secrets"
    if cmd in ("sudo", "su", "doas", "mkfs", "shred", "shutdown", "reboot", "halt", "poweroff"):
        return f"{cmd} is not allowed"
    if cmd.startswith("mkfs."):
        return f"{cmd} is not allowed"
    if cmd == "dd" and any(a.startswith("of=") for a in args):
        return "dd with of= can overwrite disks"
    if cmd in ("chmod", "chown") and any(a in ("-R", "--recursive") for a in args):
        return f"recursive {cmd}"
    if cmd == "find" and ("-delete" in args or ("-exec" in args and "rm" in args)):
        return "find with -delete/-exec rm"
    if cmd == "rm":
        return _rm_reason(args)
    if cmd == "git":
        return _git_reason(args)
    if cmd == "gh" and args[:2] in (["pr", "create"], ["pr", "merge"], ["repo", "sync"]):
        return f"gh {' '.join(args[:2])} publishes changes; ask the user"
    for word in words:
        reason = secret_path_reason(word.split("=", 1)[-1].lstrip("<>@"))
        if reason:
            return reason
    return None


def url_reason(url: str, jira_host: str | None = None) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        host.endswith("atlassian.net")
        or host.startswith("jira.")
        or (jira_host and host == jira_host.lower())
        or re.search(r"/rest/(?:api|agile)/|/browse/[A-Z][A-Z0-9_]+-\d+", parsed.path)
    ):
        return JIRA_MESSAGE
    return None


def tool_reason(
    tool: str, tool_input: Mapping[str, Any], jira_host: str | None = None
) -> str | None:
    """Why a tool call must be blocked, or None."""
    if tool == "Bash":
        return bash_reason(str(tool_input.get("command", "")), jira_host)
    if tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return secret_path_reason(str(path))
    if tool == "Grep":
        for key in ("path", "glob"):
            reason = secret_path_reason(str(tool_input.get(key) or ""))
            if reason:
                return reason
        return None
    if tool == "WebFetch":
        return url_reason(str(tool_input.get("url", "")), jira_host)
    return None


def _jira_host() -> str | None:
    base = os.environ.get("JIRA_BASE_URL")
    return urlparse(base).hostname if base else None


# ------------------------------------------------------------------------ post-edit lint


def post_edit(tool_input: Mapping[str, Any], root: Path = REPO) -> tuple[int, str]:
    path = Path(str(tool_input.get("file_path", "")))
    if path.suffix != ".py" or not path.is_file() or root.resolve() not in path.resolve().parents:
        return 0, ""
    venv_ruff = REPO / ".venv" / "bin" / "ruff"
    if venv_ruff.exists():
        ruff = [str(venv_ruff)]
    elif shutil.which("uv"):
        ruff = ["uv", "run", "--frozen", "ruff"]
    else:
        return 0, ""
    output = []
    for args in (["check", "--quiet"], ["format", "--check", "--quiet"]):
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [*ruff, *args, str(path)], cwd=root, capture_output=True, text=True, check=False
        )
        if proc.returncode:
            output.append((proc.stdout + proc.stderr).strip() or f"ruff {args[0]} failed")
    if output:
        hint = f"Fix with: uv run ruff check --fix {path} && uv run ruff format {path}"
        return 2, "\n".join([*output, hint])
    return 0, ""


# ------------------------------------------------------------------------ stop verification


def _git(*args: str) -> bytes:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *args],  # noqa: S607 - git from PATH, as Claude Code itself uses
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout


def tree_fingerprint() -> str | None:
    """Hash of everything that differs from HEAD (tracked diff + untracked, non-ignored
    files), or None when the working tree is clean."""
    status = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    if not status:
        return None
    digest = hashlib.sha256(status)
    digest.update(_git("diff", "HEAD", "--binary"))
    for name in sorted(_git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")):
        if name and (REPO / name.decode()).is_file():
            digest.update(name + b"\0" + (REPO / name.decode()).read_bytes())
    return digest.hexdigest()


def _marker() -> Path:
    return REPO / _git("rev-parse", "--git-dir").decode().strip() / "qa-assistant-verified"


def _run_verify() -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(REPO / "scripts" / "verify.sh")], cwd=REPO, capture_output=True, text=True, check=False
    )


def stop(payload: Mapping[str, Any]) -> tuple[int, str]:
    """Verify once per distinct working tree; a passing tree is remembered in .git/."""
    if payload.get("stop_hook_active") or os.environ.get("QA_SKIP_STOP_VERIFY") == "1":
        return 0, ""  # never loop: one blocked stop per failure is enough
    try:
        fingerprint = tree_fingerprint()
        marker = _marker()
    except (OSError, subprocess.CalledProcessError):
        return 0, ""
    if fingerprint is None or (marker.exists() and marker.read_text() == fingerprint):
        return 0, ""
    proc = _run_verify()
    if proc.returncode == 0:
        marker.write_text(fingerprint)
        return 0, ""
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-40:])
    return 2, (
        "scripts/verify.sh failed on the current working tree. Fix it (or tell the user "
        f"what remains) before declaring the work complete.\n{tail}"
    )


# ------------------------------------------------------------------------ entry point


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    tool_input = payload.get("tool_input") or {}
    if mode == "pre-tool":
        reason = tool_reason(str(payload.get("tool_name", "")), tool_input, _jira_host())
        code, message = (2, f"Blocked by repository hook: {reason}") if reason else (0, "")
    elif mode == "post-edit":
        code, message = post_edit(tool_input)
    elif mode == "stop":
        code, message = stop(payload)
    else:
        code, message = 1, f"usage: {argv[0]} pre-tool|post-edit|stop"
    if message:
        sys.stderr.write(message + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
