"""`IdeaProposer`: one narrow think per target (v1 `_CREATIVE_AGENDA_PROMPT`
+ `_parse_targeted_idea`, `src/main.py`, verbatim in spirit). The parser
deliberately never extracts a path from the model's response -- only
`PATCH`/`RESEARCH` + a description -- because the whole point of
diversified sampling is that the model does not choose its own target;
a model that ignores "don't second-guess the target" and states a
different file anyway must not be able to quietly redirect the
candidate (spec scenario S2). The caller (`service.py`) always sets the
candidate's `subject` to the originally sampled `Target`, never to
anything parsed from the reply.
"""

from __future__ import annotations

import re

from .api import Idea, Target, ThinkFn

PROMPT = """You are Sim, deciding your next self-improvement
priority -- nobody gave you a goal this time. This target was chosen
for you by random sampling across the whole codebase, specifically so
ideas spread across different parts of the architecture instead of
clustering wherever seems most interesting in the moment -- a real
problem observed live: asked to just "think ambitiously," this kept
returning to the same neighborhood of ideas (many worded differently
but about the same underlying thing) rather than genuinely exploring.
Trust the target; don't second-guess it by picking a different file.

Target: {path}
{content_section}

Propose ONE improvement for this specific file: either a concrete patch
you already know how to make, or -- if the right implementation
genuinely isn't clear yet -- mark it RESEARCH and describe the question
worth investigating first. Keep a patch small and targeted enough to
implement in one step.

Respond with ONLY one line, in exactly one of these two formats:
PATCH :: <one-line description of the patch>
RESEARCH :: <question or topic to investigate about this file>
No other text before or after that one line -- not even the file path,
that part is already decided."""

_LINE = re.compile(r"^\s*(PATCH|RESEARCH)\s*::\s*(.+)$", re.IGNORECASE)


def parse_targeted_idea(text: str) -> Idea | None:
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if match:
            kind = "patch" if match.group(1).upper() == "PATCH" else "research"
            return Idea(kind=kind, description=match.group(2).strip())
    return None


class TargetedIdeaProposer:
    async def propose(self, target: Target, content_preview: str, think: ThinkFn) -> Idea | None:
        content_section = f"\nCurrent content (preview):\n---\n{content_preview}\n---" if content_preview else ""
        prompt = PROMPT.format(path=target.subject, content_section=content_section)
        text, floor, _provider = await think("draft", prompt, expected="text")
        if floor or not text:
            return None
        return parse_targeted_idea(text)
