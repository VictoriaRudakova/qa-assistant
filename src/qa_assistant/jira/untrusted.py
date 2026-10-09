"""Flags instruction-like text in Jira content.

Jira text is untrusted input. This does not sanitize or rewrite anything (the analyst still
sees the original text); it gives agents a deterministic signal that a story contains text
addressed to an AI or tool rather than to a human reader, so they treat it as data. It is a
tripwire, not a defence on its own: the server-side checks (AC immutability, readiness,
export gating) are what actually stop injected instructions from taking effect.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from qa_assistant.domain.story import JiraStory

INSTRUCTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern))
    for name, pattern in (
        (
            "override_instructions",
            r"\b(?:ignore|disregard|forget|override)\b.{0,30}\b(?:previous|prior|above|earlier"
            r"|system|your|all)\b.{0,20}\b(?:instructions?|prompts?|rules|guidelines)\b",
        ),
        ("role_reassignment", r"\byou are now\b|\bact as (?:an? )?(?:ai|assistant|system)\b"),
        (
            "prompt_markup",
            r"\bsystem prompt\b|\bdeveloper message\b|</?(?:system|assistant|instructions?)>",
        ),
        ("tool_invocation", r"\bmcp__\w+|\b(?:call|invoke|run) the \w+ tool\b"),
        (
            "add_acceptance_criteria",
            r"\b(?:add|create|insert)\b.{0,20}\bacceptance criteri(?:on|a)\b",
        ),
        (
            "force_readiness",
            r"\b(?:mark|set)\b.{0,10}\b(?:all|every)\b.{0,15}\btests?(?: cases?)?\b.{0,10}"
            r"\b(?:as )?ready\b",
        ),
        (
            "bypass_review",
            r"\b(?:skip|bypass|without)\b.{0,15}\b(?:review|approval|validation)\b.{0,40}"
            r"\bexport\b|\bexport\b.{0,40}\b(?:skip|bypass|without)\b.{0,15}"
            r"\b(?:review|approval|validation)\b",
        ),
        ("shell_command", r"\bgit push\b|\brm -rf\b|\bcurl\s+https?://|\bsudo\s"),
        ("conceal", r"\bdo not (?:tell|inform|mention|show)\b.{0,15}\b(?:the )?(?:user|reviewer)"),
    )
)


def flag_instruction_like_text(sections: Iterable[tuple[str, str]]) -> list[str]:
    """Return ``"<section>: <pattern name>"`` for every section that matches a pattern."""
    flags: list[str] = []
    for section, text in sections:
        normalized = " ".join(text.casefold().split())
        flags += [
            f"{section}: {name}"
            for name, pattern in INSTRUCTION_PATTERNS
            if pattern.search(normalized)
        ]
    return flags


def story_sections(story: JiraStory) -> list[tuple[str, str]]:
    return [
        ("summary", story.summary),
        ("description", story.description),
        *((ac.id, ac.text) for ac in story.acceptance_criteria),
        *((f"comment {n}", c.body) for n, c in enumerate(story.comments, start=1)),
        *((f"link {ref.key}", ref.summary) for ref in [*story.links, *story.subtasks]),
    ]


def with_untrusted_flags(story: JiraStory) -> JiraStory:
    """Return the story with ``untrusted_instructions`` filled in."""
    return story.model_copy(
        update={"untrusted_instructions": flag_instruction_like_text(story_sections(story))}
    )
