"""Per-profile prompt scaffolds -- the `task_rules` block of Cognition's
prompt assembly (docs/blueprint/subsystems/04-cognition.md section 5.4:
"caller-supplied rules for this purpose (scope, format,
`_CAPABILITY_REFERENCE`-style tool descriptions for the tools the caller
passed)").

`Profile.scaffold` (16 section 4) was carried all the way from
`profiles.py` into `context.py::Assembler.assemble(session, purpose)` and
then dropped on the floor: nothing ever rendered it, and Cognition's
`task_rules` slot -- protected, never compacted, already implemented in
`cognition/assembler.py` -- was never filled by anyone. So a task session
reached the model with the constitution, the persona voice, the self
summary, the task description and a bare list of tool *names*, and no
statement of what finishing the task means.

Live 2026-09-07: a sandboxed `improve` run wrote its file through
`apply_source_patch` and then stopped, leaving the edit uncommitted. It
had `git_commit` in its tool list and no reason to believe it was
supposed to use it. These texts say so.
"""

from __future__ import annotations

from .api import Profile

_TOOL_NOTES: dict[str, str] = {
    "read_file": "read a file from the repo",
    "list_dir": "list a directory",
    "search_code": "grep the repo; cheaper than reading whole files to find something",
    "run_tests": "run the test suite (or a subset) and get the result back",
    "web_fetch": "fetch a URL",
    "run_python_sandboxed": "run a short Python snippet in a sandbox; no repo access",
    "apply_source_patch": "write a change to a source file",
    "apply_skill": "install or update a skill",
    "git_commit": "commit what you have applied, with a message",
    "git_revert": "undo your last commit if it turned out wrong",
    "propose_mcp_server": "propose a new MCP server to the human",
    "draft_candidate": "draft a change without applying it",
}

_PATCH = """\
You are changing your own source. Work in this order and do not stop early:

1. Find the code. Use search_code before reading whole files.
2. Apply the change with apply_source_patch. A described change is not a
   change; nothing exists until it is applied.
3. Run run_tests. If it fails, fix it and run it again.
4. Commit with git_commit. An applied but uncommitted edit is an
   unfinished task -- it is left for a human to find and clean up. Commit
   before you write your final answer, every time.

If tests still fail after your revisions, use git_revert rather than
leaving the tree broken, and say so in your final answer.

Guardian sees every tool call. A denial is an answer, not an error: say
what you were denied and stop, do not look for another route to the same
effect."""

_SKILL = """\
You are adding or changing one of your own skills. Work in this order and
do not stop early:

1. Read the existing skill, if there is one, before rewriting it.
2. Apply it with apply_skill. A described skill is not a skill.
3. Run run_tests.
4. Commit with git_commit. An applied but uncommitted change is an
   unfinished task. Commit before you write your final answer.

Guardian sees every tool call. A denial is an answer, not an error."""

_RESEARCH = """\
Answer the question from evidence you actually gathered. Read or fetch
before you conclude. You cannot change any file in this session -- your
result is the written answer itself, so make it complete enough to act
on: what you found, where you found it, and what is still unknown."""

_PLAN = """\
Produce a plan, not a change. You have read-only tools, so ground the
plan in what the code actually does today: name the real files and
functions the work touches. Give ordered steps, each one small enough to
be a single task, and say what would make the plan wrong."""

_CHAT = """\
Answer the person. Use a tool when it would make the answer true rather
than plausible, and skip the tools when you already know. Do not open
work you were not asked for."""

_BY_SCAFFOLD: dict[str, str] = {
    "patch": _PATCH,
    "skill": _SKILL,
    "research": _RESEARCH,
    "plan": _PLAN,
    "chat": _CHAT,
}


def render(profile: Profile) -> str:
    """The `task_rules` text for `profile`: its workflow, then a one-line
    note per tool it is actually allowed to call. Tools with no note are
    still listed by name -- a new tool must never silently vanish from
    the prompt just because this table has not caught up."""
    body = _BY_SCAFFOLD.get(profile.scaffold, "")
    lines = [f"- {name}: {_TOOL_NOTES[name]}" if name in _TOOL_NOTES else f"- {name}" for name in profile.tools]
    if not lines:
        return body
    tools = "Tools available to you this session:\n" + "\n".join(lines)
    return f"{body}\n\n{tools}" if body else tools


__all__ = ["render"]
