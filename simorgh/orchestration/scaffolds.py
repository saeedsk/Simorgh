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

# Filled at runtime from `capability.probed` (execution/capabilities.py),
# via `orchestration/service.py`. Module-level for the same reason
# `tools.py::register_tool_policy` is: the consumer is a pure render
# function several layers below the subscription, and threading a
# callable through Service -> Worker -> SessionRunner to deliver one
# optional line of prompt text is more machinery than the fact is
# worth. Empty in every test that does not set it, so nothing is
# said unless a probe actually failed.
_UNAVAILABLE: dict[str, tuple[str, tuple[str, ...]]] = {}


def note_capability(name: str, *, ok: bool, detail: str, tools: tuple[str, ...] | list[str]) -> None:
    if ok:
        _UNAVAILABLE.pop(name, None)
        return
    _UNAVAILABLE[name] = (detail, tuple(tools))


def unavailable_note(offered: tuple[str, ...] | list[str]) -> str:
    """What to tell the model about tools it is being offered that are
    known not to work right now. Empty when there is nothing to say --
    the common case, and it must cost nothing in the prompt."""
    lines = []
    for detail, tools in _UNAVAILABLE.values():
        affected = [t for t in tools if t in offered]
        if affected:
            lines.append(f"- {', '.join(affected)}: not working in this session ({detail})")
    if not lines:
        return ""
    return "Do not spend steps on these:\n" + "\n".join(lines)

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
    "search_listings": "search real, current for-sale property listings: first line the location, then "
                        "optional JSON filters like {\"zip_code\": \"95120\", \"max_price\": 2500000} "
                        "(unofficial data source -- see the tool's own disclaimer)",
    "geocode": "turn a free-text address into latitude/longitude",
    "browse_page": "load a page in a real browser and interact with it: click, type, wait, screenshot",
    "run_container": "run a command in a Docker container -- another language or runtime, without "
                      "installing it here; the repo is not visible inside",
    "find_package": "look up a package on PyPI or npm by name: version, age, licence, homepage",
    "install_package": "install one package with pip or npm, so you can use a library that already "
                        "does what you need",
    "run_script": "run a Python script with the repo importable and the network reachable -- the way "
                   "to actually USE an installed library",
    "notify": "send a short message to the person who runs you (their own ntfy/Gotify/Home "
               "Assistant/Matrix box, or Slack, email or SMS -- whichever is configured) -- for "
               "something they would want to know while not watching: work finished, a benchmark "
               "regressed, you are blocked. There is no unsend, and no provider may be configured, "
               "in which case it refuses and names what to set",
    "cal_list": "what is on the creator's real calendar for a range like today, tomorrow or "
                 "this week",
    "mail_search": "search the creator's real mailbox -- subjects, senders and dates, never "
                    "bodies",
    "mail_read": "open one message from mail_search and read its body",
    "remind": "set a reminder that fires even when nobody is at the terminal -- \"20m\", "
               "\"tomorrow 9am\", \"friday at 15:00\"",
    "kb_search": "search the creator's OWN documents -- their files, PDFs, notes, scans -- and "
                  "get the matching passages back with citations. For anything about their life, "
                  "house, contracts, finances or past work, look here before the web",
    "kb_ask": "ask a question of the creator's own documents and get the passages that answer it, "
               "each with a citation to quote. Says so plainly when the answer is not in there",
    "kb_open": "read more around a citation you got from kb_search or kb_ask",
    "kb_sources": "list, add, remove or scan the folders that feed the knowledge base",
    "kb_status": "how much is indexed, from where, last scanned when, and what failed",
    "run_python_sandboxed": "run a short Python snippet in a sandbox; no repo access",
    "run_js_sandboxed": "run a short JavaScript snippet with Node in a sandbox; no repo access",
    "apply_source_patch": "write a change to a source file -- or to workspace/, which is scratch: "
                           "not committed, not reviewed, and still there next session, so it is where "
                           "notes and half-finished work belong",
    "apply_skill": "install or update a skill",
    "git_commit": "commit what you have applied, with a message",
    "git_revert": "undo your last commit if it turned out wrong",
    "git_discard": "throw away an uncommitted change you decided against",
    "run_shell": "run a shell command in the repo when no other tool fits",
    "run_remote": "run a shell command on the configured remote host (a build machine, a deploy "
                   "target) -- for work that cannot happen on this box; you cannot choose the host, "
                   "and nothing here can undo what runs there",
    "web_search": "search the web for pages about something; returns titles, URLs and snippets",
    "propose_mcp_server": "propose a new MCP server to the human",
    "draft_candidate": "draft a change without applying it",
}

# A compact index of keyless data sources, generated into the RESEARCH
# scaffold rather than written twice: `docs/sourcebook.md` is the full
# table with example URLs, and a test asserts every name here appears
# there, so the prompt and the doc cannot drift apart.
#
# The failure this prevents (2026-09-09): asked for real data, Sim
# answered "no API is configured". Most public data needs no key, and
# nothing in the prompt had ever said so.
_KEYLESS_SOURCES: tuple[tuple[str, str], ...] = (
    ("weather, forecast and history", "api.open-meteo.com"),
    ("places, addresses and map data", "the geocode tool, nominatim.openstreetmap.org, overpass-api.de"),
    ("earthquakes", "earthquake.usgs.gov"),
    ("encyclopedia and structured facts", "en.wikipedia.org/api/rest_v1, wikidata.org"),
    ("papers", "export.arxiv.org, api.semanticscholar.org"),
    ("packages", "the find_package tool"),
    ("repositories", "api.github.com (60/h without a token)"),
    ("company filings", "data.sec.gov"),
    ("census and demographics", "api.census.gov"),
    ("currency rates", "open.er-api.com"),
    ("news and discussion", "hacker-news.firebaseio.com, reddit .json URLs"),
    ("for-sale property listings", "the search_listings tool"),
)


def keyless_sources_block() -> str:
    lines = [f"- {what}: {where}" for what, where in _KEYLESS_SOURCES]
    return (
        "Most public data needs no API key. Before concluding that something cannot be "
        "fetched, try one of these -- web_fetch returns a JSON body untouched, and "
        "docs/sourcebook.md has the exact URLs:\n" + "\n".join(lines)
    )


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
_RESEARCH = _RESEARCH + "\n\n" + keyless_sources_block()

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


def render(profile: Profile, *, subject: str | None = None, task: str | None = None,
           unavailable: str = "") -> str:
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
    # A tool that is offered but known to be down right now (its binary
    # missing, its optional package uninstalled). Saying so costs one
    # line and saves the three steps it takes to discover by failing --
    # and nothing is said at all when everything works, which is the
    # common case (kernel/capabilities.py).
    if unavailable:
        tools = f"{tools}\n\n{unavailable}"
    return f"{body}\n\n{tools}" if body else tools


__all__ = ["render"]
