"""Projects: a goal decomposed into an ordered set of child tasks (patch
and/or research), the third tier of Sim's work harness alongside a plain
Task (src/orchestrator/tasks.py) and a Research task
(src/orchestrator/research_task.py). Some ideas are genuinely too big for
one patch -- forcing them through the flat one-shot task pipeline either
produces something too shallow to be worth much, or (observed live,
repeatedly) the same broad idea gets independently re-proposed and
re-drafted several times over because nothing tracked it as one ongoing
initiative with real sub-steps.

A project is never itself run through propose_self_patch/propose_skill --
it has no `subject`, and "working" one means working its next unfinished
child (see main.py's _next_task/run_task, which unwrap a PROJECT_TASK to
its children rather than dispatching the project itself). This module
only owns decomposition (turning a goal into real child Tasks, linked via
the Task schema's existing `parent_id` field -- no new persistence layer)
and the pure status rollup a project's own completion is computed from.
"""

from __future__ import annotations

import re

from src.cognition.provider import CognitionRouter
from src.orchestrator.audit import PROTECTED_SUBJECTS
from src.orchestrator.tasks import (
    BLOCKED,
    DONE,
    FAILED,
    IN_PROGRESS,
    PATCH_TASK,
    PENDING,
    RESEARCH_TASK,
    TERMINAL_STATUSES,
    Task,
    TaskStore,
)

DEFAULT_PROJECT_STEP_COUNT = 4

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
{count}. <...>
No other text before or after the list."""

_PATCH_LINE = re.compile(r"^\s*\d+[.):]\s*(\S+)\s*::\s*(.+)$")
_RESEARCH_LINE = re.compile(r"^\s*\d+[.):]\s*RESEARCH\s*::\s*(.+)$", re.IGNORECASE)


def parse_project_steps(text: str, expected_count: int) -> list[tuple[str, str | None, str]]:
    """Returns (kind, subject, description) triples -- subject is None
    for a RESEARCH step. Checks the RESEARCH form first: it would also
    match `_PATCH_LINE` (with "RESEARCH" captured as the "path"), so
    order here is what keeps a research step from being misfiled as a
    patch targeting a file literally named "RESEARCH".
    """
    steps: list[tuple[str, str | None, str]] = []
    for line in text.splitlines():
        research_match = _RESEARCH_LINE.match(line)
        if research_match:
            steps.append((RESEARCH_TASK, None, research_match.group(1).strip()))
            continue
        patch_match = _PATCH_LINE.match(line)
        if not patch_match:
            continue
        path, description = patch_match.group(1).strip(), patch_match.group(2).strip()
        if path.startswith("src/") and "src/agents/skills/" not in path and description:
            steps.append((PATCH_TASK, path, description))
    return steps[:expected_count]


def decompose_project(
    cognition: CognitionRouter,
    task_store: TaskStore,
    project: Task,
    files: list[str],
    count: int = DEFAULT_PROJECT_STEP_COUNT,
) -> list[Task]:
    """Turns `project`'s goal into `count` real child Tasks (patch and/or
    research), each linked via `parent_id=project.id`. Deterministic-
    fallback-safe like every other drafting call in this codebase:
    returns an empty list rather than a fabricated plan when no real
    provider answers -- a project with no children yet is simply
    PENDING (see project_status below), not broken, and gets decomposed
    on the next attempt.
    """
    response = cognition.complete(
        _DECOMPOSE_PROMPT.format(
            goal=project.description, count=count, files="\n".join(files) or "(none found)"
        )
    )
    if response.provider_name == "deterministic_fallback":
        return []

    steps = parse_project_steps(response.text, count)
    children: list[Task] = []
    for kind, path, description in steps:
        if kind == PATCH_TASK and any(protected in path for protected in PROTECTED_SUBJECTS):
            continue
        child = task_store.add(
            description, kind, subject=path, discovered_via="project", parent_id=project.id
        )
        children.append(child)
    return children


def project_status(children: list[Task]) -> str:
    """The project's own status, purely a function of its children's
    current statuses -- never persisted as independent state, so it can
    never drift out of sync with what actually happened to them.
    """
    if not children:
        return PENDING
    statuses = [c.status for c in children]
    if all(s == DONE for s in statuses):
        return DONE
    if all(s in TERMINAL_STATUSES for s in statuses):
        # every child finished, but not all succeeded -- see DONE check
        # above, so this only reaches here when at least one is FAILED.
        return FAILED
    if any(s == IN_PROGRESS for s in statuses):
        return IN_PROGRESS
    if any(s == DONE for s in statuses):
        # some children finished, others haven't started yet -- still
        # actively progressing, not merely pending.
        return IN_PROGRESS
    if any(s == BLOCKED for s in statuses):
        return BLOCKED
    return PENDING


def next_unfinished_child(children: list[Task]) -> Task | None:
    """The next child worth working on, in creation (i.e. planned) order
    -- the direct mechanism behind "working a project means working its
    next unfinished child." `children` is expected in TaskStore.children's
    own creation-ordered return, so this doesn't re-sort.
    """
    for child in children:
        if child.status not in TERMINAL_STATUSES:
            return child
    return None
