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
from .tools import offered_tools

_TOOL_NOTES: dict[str, str] = {
    "self_map": "ask your own world model what real subsystems/files make you up -- the authoritative "
                "answer for questions about your own code or architecture; simorgh/ is what runs, src/ is retired v1",
    "read_file": "read a file from the repo, including a PDF (papers/ holds papers)",
    "list_dir": "list a directory",
    "search_code": "grep the repo; cheaper than reading whole files to find something",
    "run_tests": "run the test suite (or a subset) and get the result back",
    "web_fetch": "fetch a URL; HTML comes back as text and a PDF as its text",
    "render_page": "load a URL or repo-local file in a real headless browser; "
                    "reports title, visible text, JS errors, and failed network requests",
    "search_listings": "search real, current for-sale property listings by location, with price/sqft filters "
                        "(unofficial data source -- see the tool's own disclaimer)",
    "geocode": "turn a free-text address into latitude/longitude",
    "run_python_sandboxed": "run a short Python snippet in a sandbox; no repo access",
    "run_js_sandboxed": "run a short JavaScript snippet with Node in a sandbox; no repo access",
    "apply_source_patch": "write a change to a source file",
    "apply_skill": "install or update a skill",
    "git_commit": "commit what you have applied, with a message",
    "git_revert": "undo your last commit if it turned out wrong",
    "git_discard": "throw away an uncommitted change you decided against",
    "run_shell": "run a shell command in the repo when no other tool fits",
    "web_search": "search the web for pages about something; returns titles, URLs and snippets",
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
5. After a successful commit you are done: write your final answer in
   plain text with no tool marker -- what you changed and why. Do not
   read the file back, re-run the tests, or apply it again.

If tests still fail after your revisions, put the tree back before you
finish -- git_discard on the file you changed if you have not committed
it, git_revert if you have -- and say in your final answer what you tried
and why you undid it. Never leave a broken change sitting in the tree.

Guardian sees every tool call. A denial is an answer, not an error: say
what you were denied and stop, do not look for another route to the same
effect."""

_SKILL = """\
You are adding or changing one of your own skills. Work in this order and
do not stop early:

1. Read the existing skill, if there is one, before rewriting it. For a
   brand-new skill, skip this -- the read will only be refused.
2. Apply it with apply_skill. A described skill is not a skill.
3. Run it once with run_python_sandboxed and check the answer is right:
   import it and call it with a real argument. run_tests reports "no
   tests cover this target" for a new file, which proves nothing, and a
   skill asserted to work rather than seen to work is not finished.
4. Commit with git_commit. An applied but uncommitted change is an
   unfinished task. Commit before you write your final answer.
5. After a successful commit you are done: write your final answer in
   plain text with no tool marker. Do not read it back or apply it again.

Guardian sees every tool call. A denial is an answer, not an error."""

_RESEARCH = """\
Answer the question from evidence you actually gathered. Read or fetch
before you conclude. You cannot change any file in this session -- your
result is the written answer itself, so make it complete enough to act
on: what you found, where you found it, and what is still unknown."""

# The format below is not decoration: Planning parses this answer with
# `planning/decomposer.py::parse_steps`, which reads exactly these two
# line shapes and silently ignores everything else. Live-caught
# 2026-09-07: the scaffold said only "give ordered steps", so the model
# answered in prose with markdown headings, `parse_steps` found nothing,
# and Planning took its "decomposition produced no real steps" branch --
# every time. All 21 of the creator's projects sat at 0/0 steps and not
# one task in the whole ledger had a parent. The producer and the parser
# had never been told the same thing.
_PLAN = """\
Produce a plan, not a change. You have read-only tools, so ground the
plan in what the code actually does today: read before you decide, and
name the real files the work touches.

Your final answer must be ONLY a numbered list, one step per line, each
line in exactly one of these two forms:

  1. simorgh/<path>.py :: what to change in that file and why
  2. RESEARCH :: a question to settle before the later steps

Order matters: a RESEARCH step that informs later steps comes first.
Name a real path you have actually looked at. Anything that is not one
of those two line shapes is discarded, so no preamble, no headings, no
prose after the list -- the list is the whole answer."""

_CHAT = """\
Answer the person. Use a tool when it would make the answer true rather
than plausible, and skip the tools when you already know. Do not open
work you were not asked for.

A question about your own code, architecture or subsystems is answered
by self_map, not by list_dir or exploring the tree by hand -- it asks
your own world model directly and is always current. `simorgh/` is the
live code you actually run; `src/` is retired v1 code kept around for
reference only -- it still exists, but it is not where you live now, so
do not describe it as your current structure unless asked specifically
about the old v1 code."""

# The creator, 2026-09-09, after watching another agent solve "real
# estate listings, no API key" by finding an open-source package on PyPI
# while Sim stopped at "no data source is configured": "adjust your
# mindset to be resourceful to unblock itself and get the task done."
# Offered only where run_shell is, since that is the one tool that can
# actually install something and run it with network access.
_RESOURCEFUL = """\
A missing capability is not a denial. If the task needs something you
have no tool for -- live data, a file format, a service with no key
configured -- do not stop at "not configured" or "needs an API key".
First look for an existing open-source package, MCP server, container,
or keyless public API that already does it: web_search finds them, and
run_shell can `pip install` a package and run a script. Guardian
refuses code that opens the network by hand (urllib, requests, socket)
in run_python_sandboxed, but an installed library that does that work
for you is fine to import and call there. Use it, and say plainly what
it is and what its limits are: unofficial, may break, terms of service.
Stop only after you have actually looked and found nothing, and then
say what you looked for. A Guardian denial is different -- that is an
answer, and you do not route around it."""

_BY_SCAFFOLD: dict[str, str] = {
    "patch": _PATCH,
    "skill": _SKILL,
    "research": _RESEARCH,
    "plan": _PLAN,
    "chat": _CHAT,
}


def render(profile: Profile, *, subject: str | None = None, task: str | None = None) -> str:
    """The `task_rules` text for `profile`: its workflow, then a one-line
    note per tool it is actually allowed to call. Tools with no note are
    still listed by name -- a new tool must never silently vanish from
    the prompt just because this table has not caught up."""
    body = _BY_SCAFFOLD.get(profile.scaffold, "")
    if body and "run_shell" in profile.tools:
        body = f"{body}\n\n{_RESOURCEFUL}"
    if task:
        # The task belongs in `task_rules` because that block is
        # *protected* -- never compacted (04 section 4.6). As a plain user
        # turn it lived in the elastic conversation, so a large tool
        # result could push it out. Live-caught 2026-09-07: once the model
        # was finally shown a whole file, its very next reply was "I have
        # the full file in hand, but the change itself was never
        # specified" -- it had read the file it was asked to edit and no
        # longer knew what it had been asked to do.
        body = f"Your task: {' '.join(task.split())}\n\n{body}" if body else f"Your task: {task}"
    if subject and profile.scaffold in ("patch", "skill"):
        # Live-caught 2026-09-07: handed a task that named the exact file,
        # the model spent all eight of its steps searching the repo --
        # including the retired v1 tree and the docs -- and was then forced
        # to give a final answer having applied nothing. It had the path
        # the whole time. Step 1 of the workflow is "find the code"; when
        # the task already says where it is, that step is a trap.
        body = (
            f"The file is `{subject}`. You already have it -- read that file first and "
            f"do not go looking for it.\n\n" + body
        )
    offered = offered_tools(profile.tools)
    lines = [f"- {name}: {_TOOL_NOTES[name]}" if name in _TOOL_NOTES else f"- {name}" for name in offered]
    if not lines:
        return body
    # The parser runs the FIRST marker in a reply and ignores the rest.
    # Nothing said so, so the model batched calls and lost most of them
    # -- three observers independently watched whole halves of a task
    # disappear this way (2026-09-08).
    tools = (
        "One tool call per message: write a single marker line, and wait for its result "
        "before asking for the next. Anything after the first marker is ignored.\n\n"
        "Tools available to you this session:\n" + "\n".join(lines)
    )
    return f"{body}\n\n{tools}" if body else tools


__all__ = ["render"]
