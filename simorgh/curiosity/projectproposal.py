"""`ProjectProposer`: the deliberately rare, deliberately open-ended
exception to "always sample first" (v1 `discover_creative_project`,
`src/main.py`). A project spans more ground than one diversified-sampling
target could represent, so this is the one place a model still picks its
own focus -- appropriate here, not a relapse of the collapse this
package otherwise exists to prevent (spec section 5.4).
"""

from __future__ import annotations

import re

from .api import ThinkFn

PROMPT = """You are Sim, deciding whether now is a good moment
to start a genuinely ambitious, multi-step self-improvement project --
not a single small patch, a real initiative worth breaking into several
coordinated steps (some of which may be research, if the right approach
isn't obvious yet).

Files that already exist in this codebase (for context; a project step
can revise one of these or introduce something new):
{files}

Propose ONE ambitious goal worth this kind of coordinated effort. Respond
with ONLY one line:
GOAL :: <one-sentence description of the ambitious goal>
No other text before or after that line."""

_LINE = re.compile(r"^\s*GOAL\s*::\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def parse_goal(text: str) -> str | None:
    match = _LINE.search(text)
    if match is None:
        return None
    goal = match.group(1).strip()
    return goal or None


class OpenEndedProjectProposer:
    async def propose(self, files: list[str], think: ThinkFn) -> str | None:
        prompt = PROMPT.format(files="\n".join(files) or "(none found)")
        text, floor, _provider = await think("plan", prompt, expected="text")
        if floor or not text:
            return None
        return parse_goal(text)
