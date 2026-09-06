"""`parse_steps` (port of v1 `parse_project_steps`, `src/orchestrator/projects.py`)
and `decompose` (issues `cognition.think(purpose="decompose")` and parses
the reply) -- spec section 5.4 step 1-2 and section 3.4's `Decomposer`
protocol."""

from __future__ import annotations

import re
import uuid
from typing import Protocol

from .model import Step

_PATCH_LINE = re.compile(r"^\s*\d+[.):]\s*(\S+)\s*::\s*(.+)$")
_RESEARCH_LINE = re.compile(r"^\s*\d+[.):]\s*RESEARCH\s*::\s*(.+)$", re.IGNORECASE)

_DECOMPOSE_PROMPT = """You are Sim, breaking a project goal down into a
concrete, ordered set of steps -- not doing the work itself, just
planning it.

Project goal: {goal}

Files that already exist in this codebase (prefer revising one of
these when it genuinely fits; naming a new path under src/ is fine
too, for something genuinely new):
{files}

Break this into {count} concrete steps toward the goal. Each step is
either a specific patch to make, or an open question worth researching
before committing to an approach. Use RESEARCH for a step whose right
implementation genuinely isn't clear yet; use a real file path for a
step you already know how to make. Order matters -- research steps
that inform later patches should come first.

Respond with ONLY a numbered list, one per line, in exactly one of
these two formats:
1. <repo-relative path under src/> :: <description of the patch>
2. RESEARCH :: <question or topic to investigate>
...
No other text before or after the list."""


def parse_steps(text: str, expected: int) -> list[Step]:
    """Returns up to `expected` `Step`s. A RESEARCH line is checked
    first: it would also match `_PATCH_LINE` (with "RESEARCH" captured
    as the path), so order is what keeps a research step from being
    misfiled as a patch targeting a file literally named "RESEARCH"."""
    steps: list[Step] = []
    prior_research: list[str] = []
    for line in text.splitlines():
        research_match = _RESEARCH_LINE.match(line)
        if research_match:
            sid = uuid.uuid4().hex[:8]
            steps.append(Step(
                step_id=sid, kind="research", description=research_match.group(1).strip(),
                depends_on=(), why="from project decomposition",
            ))
            prior_research.append(sid)
            continue
        patch_match = _PATCH_LINE.match(line)
        if not patch_match:
            continue
        path, description = patch_match.group(1).strip(), patch_match.group(2).strip()
        if path.startswith("src/") and "src/agents/skills/" not in path and description:
            # Default edge (spec 5.4 step 4): a research step is a
            # dependency of every later patch step, per the prompt's own
            # ordering instruction.
            steps.append(Step(
                step_id=uuid.uuid4().hex[:8], kind="patch", description=description,
                depends_on=tuple(prior_research), why="from project decomposition", subject=path,
            ))
        if len(steps) >= expected:
            break
    return steps[:expected]


class CognitionCaller(Protocol):
    async def think(self, *, purpose: str, prompt: str, require_real_provider: bool = False) -> str | None:
        """Returns the reply text, or None on a floor/non-answer."""
        ...


async def decompose(caller: CognitionCaller, goal: str, files: list[str], count: int) -> list[Step]:
    prompt = _DECOMPOSE_PROMPT.format(goal=goal, count=count, files="\n".join(files) or "(none found)")
    text = await caller.think(purpose="decompose", prompt=prompt)
    if not text:
        return []
    return parse_steps(text, count)


__all__ = ["decompose", "parse_steps", "CognitionCaller"]
