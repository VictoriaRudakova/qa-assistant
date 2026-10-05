"""Normalize Jira rich text to the plain-text convention of
:mod:`qa_assistant.jira.acceptance_criteria`.

* Cloud returns Atlassian Document Format (ADF, a JSON tree): :func:`adf_to_text`.
* Data Center returns wiki markup: :func:`wiki_to_text`.

Both are lossy on purpose: only structure that matters for QA analysis (headings, lists,
paragraphs, bold-only heading lines, tables as ``a | b`` rows) survives.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

_LIST_TYPES = frozenset({"bulletList", "orderedList", "taskList"})
_SKIPPED_BLOCKS = frozenset({"rule", "mediaSingle", "mediaGroup", "media", "extension"})
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def adf_to_text(document: Any) -> str:
    """Render an ADF document (or any ADF node) as plain text."""
    if not isinstance(document, Mapping):
        return ""
    if document.get("type") == "doc":
        text = "\n\n".join(_blocks(_children(document)))
    else:
        text = _block(document)
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    content = node.get("content")
    if not isinstance(content, list):
        return []
    return [child for child in content if isinstance(child, Mapping)]


def _attrs(node: Mapping[str, Any]) -> Mapping[str, Any]:
    attrs = node.get("attrs")
    return attrs if isinstance(attrs, Mapping) else {}


def _blocks(nodes: list[Mapping[str, Any]], depth: int = 0) -> list[str]:
    return [block for node in nodes if (block := _block(node, depth)).strip()]


def _block(node: Mapping[str, Any], depth: int = 0) -> str:
    kind = node.get("type")
    if kind in _SKIPPED_BLOCKS:
        return ""
    if kind == "paragraph":
        return _inline(_children(node))
    if kind == "heading":
        level = _attrs(node).get("level")
        hashes = "#" * (level if isinstance(level, int) and 1 <= level <= 6 else 1)
        return f"{hashes} {_inline(_children(node))}"
    if kind in _LIST_TYPES:
        return "\n".join(_list_lines(node, depth))
    if kind == "codeBlock":
        return _inline(_children(node))
    if kind == "table":
        return "\n".join(_table_rows(node))
    if kind == "text" or not _children(node):
        return _inline([node])
    # blockquote, panel, expand, layouts and unknown containers: render their content.
    return "\n\n".join(_blocks(_children(node), depth))


def _list_lines(node: Mapping[str, Any], depth: int) -> list[str]:
    kind = node.get("type")
    start = _attrs(node).get("order")
    number = start if isinstance(start, int) else 1
    indent = "  " * depth
    lines: list[str] = []
    for item in _children(node):
        if item.get("type") in _LIST_TYPES:  # taskList nests lists directly
            lines.extend(_list_lines(item, depth + 1))
            continue
        if kind == "orderedList":
            marker = f"{number}."
            number += 1
        elif kind == "taskList":
            marker = "- [x]" if _attrs(item).get("state") == "DONE" else "- [ ]"
        else:
            marker = "-"
        if item.get("type") == "taskItem":  # task items hold inline content directly
            lines.append(f"{indent}{marker} {_inline(_children(item))}".rstrip())
            continue
        first = True
        for child in _children(item):
            if child.get("type") in _LIST_TYPES:
                lines.extend(_list_lines(child, depth + 1))
                continue
            text = _block(child, depth + 1)
            if not text.strip():
                continue
            prefix = f"{indent}{marker} " if first else f"{indent}  "
            lines.append(prefix + text.replace("\n", f"\n{indent}  "))
            first = False
    return lines


def _table_rows(node: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for row in _children(node):
        cells = [" ".join(_blocks(_children(cell))).replace("\n", " ") for cell in _children(row)]
        if any(cell.strip() for cell in cells):
            rows.append(" | ".join(cell.strip() for cell in cells))
    return rows


def _inline(nodes: list[Mapping[str, Any]]) -> str:
    parts: list[str] = []
    for node in nodes:
        kind = node.get("type")
        attrs = _attrs(node)
        if kind == "text":
            text = str(node.get("text", ""))
            if text.strip() and _has_mark(node, "strong"):
                text = f"**{text}**"
            parts.append(text)
        elif kind == "hardBreak":
            parts.append("\n")
        elif kind in {"mention", "status"}:
            parts.append(str(attrs.get("text", "")))
        elif kind == "emoji":
            parts.append(str(attrs.get("text") or attrs.get("shortName", "")))
        elif kind in {"inlineCard", "blockCard"}:
            parts.append(str(attrs.get("url", "")))
        elif kind == "date":
            parts.append(_adf_date(attrs.get("timestamp")))
        else:
            parts.append(_inline(_children(node)))
    return "".join(parts)


def _has_mark(node: Mapping[str, Any], mark: str) -> bool:
    marks = node.get("marks")
    return isinstance(marks, list) and any(
        isinstance(m, Mapping) and m.get("type") == mark for m in marks
    )


def _adf_date(timestamp: Any) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp) / 1000, tz=UTC).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


# --------------------------------------------------------------------------- wiki markup

_WIKI_BLOCK_MACRO_RE = re.compile(
    r"^\s*\{(?:code|noformat|quote|panel|color)(?::[^}]*)?\}\s*$", re.IGNORECASE
)
_WIKI_NUMBERED_RE = re.compile(r"^(?P<level>#+)\s+(?P<text>.*)$")
_WIKI_BULLET_RE = re.compile(r"^(?P<level>[*-]+)\s+(?P<text>.*)$")
_WIKI_LINK_RE = re.compile(r"\[(?:(?P<label>[^|\]]+)\|)?(?P<target>[^\]]+)\]")
_WIKI_TABLE_RE = re.compile(r"\|\|?")


def wiki_to_text(markup: str) -> str:
    """Render Jira wiki markup as plain text."""
    lines: list[str] = []
    for raw in markup.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if _WIKI_BLOCK_MACRO_RE.match(line):
            continue
        line = _WIKI_LINK_RE.sub(lambda m: m.group("label") or m.group("target"), line)
        line = line.replace("\\\\", "\n")
        if numbered := _WIKI_NUMBERED_RE.match(line):
            depth = len(numbered.group("level")) - 1
            line = f"{'  ' * depth}1. {numbered.group('text')}"
        elif bullet := _WIKI_BULLET_RE.match(line):
            depth = len(bullet.group("level")) - 1
            line = f"{'  ' * depth}- {bullet.group('text')}"
        elif line.startswith("|"):
            cells = [c.strip() for c in _WIKI_TABLE_RE.split(line) if c.strip()]
            line = " | ".join(cells)
        lines.append(line)
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()
