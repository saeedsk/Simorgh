"""ToolCallRouter (16 section 5): a `cognition.think` tool_call becomes an
`action.proposed` payload. Guardian is the sole authority on whether it's
actually approved -- this only tags the request with the reversibility/
scope Guardian's policy reads (03 section 4.6).

v1's full 14-marker conversational set (PROPOSE/PATCH/BATCH/PLAN/EVOLVE/
USE/NEWS/GROWTH/FETCH/RUN/READ/LIST/RECALL/REMIND) is NOT implemented
this session -- only the plain tool_calls -> action.proposed path is.
See 16 section 12 Q4/Q5 and this package's README "Not done this session".
"""

from __future__ import annotations

import json
import re

# (reversibility, network) per known tool name -- conservative default
# for anything unlisted: irreversible, so an unrecognized tool never
# accidentally gets read_only's lighter Guardian scrutiny.
_TOOL_POLICY: dict[str, tuple[str, bool]] = {
    "read_file": ("read_only", False),
    "list_dir": ("read_only", False),
    "search_code": ("read_only", False),
    "self_map": ("read_only", False),
    "web_fetch": ("read_only", True),
    "web_search": ("read_only", True),
    "render_page": ("read_only", True),
    "browse_page": ("reversible", True),
    "search_listings": ("read_only", True),
    "geocode": ("read_only", True),
    "find_package": ("read_only", True),
    "run_python_sandboxed": ("reversible", False),
    "run_js_sandboxed": ("reversible", False),
    "run_tests": ("reversible", False),
    "draft_candidate": ("reversible", False),
    # Model-callable since 2026-09-07 (profiles.py's own note): the tools
    # that actually land a change. Each declares itself `reversible` in
    # execution/tools.py (git_revert exists precisely so they are), so
    # Guardian auto-allows them in guarded posture; ProtectedRule and
    # DenylistRule still run first and still deny outright.
    "apply_source_patch": ("reversible", False),
    "apply_skill": ("reversible", False),
    "git_commit": ("reversible", False),
    "git_revert": ("reversible", False),
    "git_discard": ("reversible", False),
    # A shell can reach the network and anything else on the machine;
    # Guardian gates every call on `irreversible` (execution/shell.py).
    "run_shell": ("irreversible", True),
    # Each changes this machine and reaches the network: gated like run_shell.
    "install_package": ("irreversible", True),
    "run_script": ("irreversible", True),
    "run_container": ("irreversible", True),
    # `notify` reaches a PERSON, which nothing else in this table does.
    # Irreversible in the strongest sense available: there is no unsend,
    # so a message sent in error cannot be walked back the way
    # `git_revert` walks back a commit. With
    # `irreversible_requires_human` set, every message waits for
    # approval; a deployment that auto-approves has chosen that.
    "notify": ("irreversible", True),
    # Runs on a machine this process cannot inspect, snapshot or roll
    # back -- the strongest case for `irreversible` in the table.
    "run_remote": ("irreversible", True),
    # -- MCP (execution/mcp.py's own module docstring): a human adds an
    # entry here, by the server's registered tool name
    # (`mcp_<server>_<tool>`), for every MCP tool they want the model to
    # actually be able to call -- registering the server alone (Guardian
    # would still gate the call) is not enough, since a marker-driven
    # call also needs the remap below. ddg_search/ddg_get_answer (free,
    # no API key -- `ddg-search-mcp` on npm) are the two wired end-to-end
    # this pass; README.md's "MCP servers" section has the matching
    # `mcp_servers` config entry.
    "mcp_ddg_search_ddg_search": ("read_only", True),
    "mcp_ddg_search_ddg_get_answer": ("read_only", True),
    # `propose_mcp_server` (execution/tools.py's own docstring has the
    # full history -- changed same day from `irreversible` to
    # `reversible`, the creator: "sim should just create it, period ...
    # remove any rule that prevents it") only records a proposal, never
    # installs or runs anything, so Guardian auto-allows it in guarded
    # posture without that being a real capability grant. The actual
    # boundary is downstream and absolute: only the `mcp` CLI command
    # ever writes `simorgh.toml`, and nothing in the tool-calling
    # pipeline can reach that code path in any posture -- not a Guardian
    # policy this entry could loosen, a structural one.
    "propose_mcp_server": ("reversible", False),
}

# `cognition/parser.py::_parse_markers` only ever extracts one string per
# marker line -- `{"argument": <str>}` (v1's marker vocabulary was
# single-argument by design; see this package's README "Not done this
# session"). Real tool `args_schema`s use a tool-specific key (`path`,
# `url`, `code`), so a marker-shaped call has to be remapped onto that
# key before Execution ever sees it -- live-caught: without this, every
# real tool call from a marker reply failed with a bare `KeyError` on its
# own required arg (e.g. `web_fetch` needs `url`, not `argument`).
_MARKER_ARG_KEY: dict[str, str] = {
    "read_file": "path",
    "list_dir": "path",
    "search_code": "query",
    # Its one optional argument -- see execution/tools.py::SelfMapTool. A
    # bare `SELF_MAP:` marker with no argument still works: `args.get`
    # treats an empty string the same as "no area given".
    "self_map": "area",
    "web_fetch": "url",
    "web_search": "query",
    "render_page": "target",
    "geocode": "address",
    "find_package": "query",
    "run_script": "code",
    "run_python_sandboxed": "code",
    "run_js_sandboxed": "code",
    "run_tests": "target",
    # Absent until 2026-09-08, so every `RUN_SHELL:` marker arrived as
    # `{"argument": ...}` while the tool reads `command`, and answered
    # "refused: no command given". The tool had never once run from the
    # model's side; two observers found it independently.
    "run_shell": "command",
    "run_remote": "command",
    # Same defect as run_shell, found by the audit the same day:
    # `GIT_DISCARD: path` arrived as `{"argument": ...}` while the tool
    # reads `path`, so it answered "refused: name the path to discard".
    # It is the tool that backs out a bad uncommitted edit -- the
    # "never leave a broken change in the tree" net -- and it had never
    # once worked from the model's side.
    "git_discard": "path",
    "draft_candidate": "code",
    # ddg_search/ddg_get_answer's own `inputSchema`s each have one
    # required string field, `query` -- see `_TOOL_POLICY`'s comment on
    # the same tools.
    "mcp_ddg_search_ddg_search": "query",
    "mcp_ddg_search_ddg_get_answer": "query",
    # `propose_mcp_server` has a genuinely multi-field schema (name,
    # command, args, ...), but its one `args_schema` property is a
    # single free-form text block the tool parses itself
    # (`_parse_mcp_proposal_text`), so it's still single-argument at the
    # marker layer -- see the tool's own docstring.
    "propose_mcp_server": "proposal",
}

# Live-caught (the creator, real use): told to use `propose_mcp_server`,
# the model wrote `PROPOSE_MCP_SERVER: {"name": "...", "description":
# "...", "reason": "..."}` -- valid-looking JSON, wrong field
# (`description` isn't real), no `command` at all. Nothing had ever told
# it the tool's *own* expected sub-format -- the general marker
# instruction (`cognition/service.py::_tool_instruction_block`) only
# ever named the tool, never its argument shape, and Cognition can't
# read `execution/tools.py`'s own `description` field itself (crossing
# the subsystem boundary `test_module_boundaries.py` enforces). A short,
# hand-maintained hint here, threaded through `cognition.think`'s
# `tool_hints` field (`session.py::_think`) and surfaced by that same
# instruction block, is the fix -- only tools whose one marker argument
# has real internal structure need an entry; a bare path/url/code
# argument is self-explanatory from the tool's own name.
_MARKER_ARG_HINT: dict[str, str] = {
    "self_map": (
        "leave this blank for the full map, or name one real subsystem "
        "(e.g. worldmodel, cognition) to see just its files -- do not "
        "describe what you want in prose, it is matched literally"
    ),
    "read_file": (
        "a repo path, optionally with an inclusive 1-based line range, e.g. "
        "simorgh/foo.py:120-260. A result is cut at ~8000 chars, so read a "
        "large file in ranges rather than trusting a cut result as the whole file"
    ),
    "web_search": (
        "plain search words, as you would type into a search box -- not a "
        "sentence and not a URL. It returns titles, URLs and snippets; read "
        "one with WEB_FETCH to get the page itself"
    ),
    "propose_mcp_server": (
        "key: value lines, one per line -- name (lowercase_snake_case), "
        "command (one of npx/uvx/node/python/python3), args (comma-separated, optional), "
        "reason (required, why this server is needed). Example:\n"
        "name: web_search\ncommand: npx\nargs: -y, some-mcp-package\nreason: real web search, no key needed"
    ),
}


# Two-field tools reachable through the one-string marker layer: the
# first line of the payload is the first key, everything after it the
# second. `cognition/parser.py::_CODE_BEARING_MARKERS` keeps the payload
# multi-line for exactly these names.
_MARKER_SPLIT_FIRST_LINE: dict[str, tuple[str, str]] = {
    "apply_source_patch": ("subject", "code"),
    "apply_skill": ("subject", "code"),
    "git_commit": ("path", "message"),
    "search_listings": ("location", "filters"),
    "browse_page": ("target", "actions"),
    "run_container": ("image", "command"),
    "install_package": ("manager", "spec"),
    "notify": ("subject", "body"),
}
_MARKER_ARG_HINT.update({
    "apply_source_patch": (
        "first line: the repo-relative file path to write -- simorgh/, simorgh_skills/, "
        "tests/, tools/ or docs/ (NOT src/, which is the retired v1 tree and is read-only); "
        "a refusal names the writable areas. Every "
        "following line: the COMPLETE new content of that file -- it replaces "
        "the whole file, so anything you leave out is deleted. Read the whole "
        "file (no line range) before rewriting it. Example:\n"
        "APPLY_SOURCE_PATCH: simorgh/foo.py\ndef f():\n    return 1\n"
    ),
    "apply_skill": (
        "first line: the skill module path (inside simorgh_skills/); every "
        "following line: the complete module source, defining run(**args)."
    ),
    "git_commit": "first line: the one path to commit; second line: the commit message.",
    "git_revert": "no argument -- write just the marker: GIT_REVERT:",
    "git_discard": "the one path whose uncommitted changes to throw away.",
    "run_tests": "a test file or directory to run (e.g. tests/simorgh/guardian), or empty for the whole suite.",
    "search_code": "a regular expression to search for across the readable tree.",
    "run_shell": "one shell command, run from the repository root; its output comes back to you.",
    "run_remote": (
        "one shell command, run on the configured remote host. You do NOT choose the host -- it is "
        "fixed by configuration, and there is no way to name a different one. Nothing here can undo "
        "what runs there, so read before you write."
    ),
    # Code-bearing: the ENTIRE rest of the message is the program. Found
    # by trial 2026-09-07: with no hint the model wrote its code and then
    # kept talking, and the prose became part of the program -- a
    # SyntaxError on the em-dash in its own commentary, every first call.
    "run_python_sandboxed": (
        "every line after the marker is the Python program, and nothing else -- "
        "no explanation before or after it. Example:\nRUN_PYTHON_SANDBOXED:\nprint(2 + 2)\n"
    ),
    "search_listings": (
        "first line: the location only (e.g. `San Jose, CA 95120`). Every following "
        "line, optional: a JSON object of filters, e.g. "
        '{"zip_code": "95120", "min_sqft": 1500, "max_price": 2500000}. '
        "Do NOT put filters in the first line as prose -- the whole line is read as "
        "the location and will match nothing."
    ),
    "run_js_sandboxed": (
        "every line after the marker is the JavaScript program, run with Node, and nothing else -- "
        "no explanation before or after it. Example:\nRUN_JS_SANDBOXED:\nconsole.log(2 + 2)\n"
    ),
    # Live-caught 2026-09-09 (tools audit): these four hints were pasted
    # into `_TOOL_POLICY` by mistake instead of here -- a duplicate
    # `"browse_page"` key in that dict literal even silently overwrote
    # its real `(reversibility, network)` tuple with this hint STRING,
    # so every `BROWSE_PAGE:` marker crashed `to_action_payload` trying
    # to unpack a string into two variables. Moved to the table they
    # actually belong in.
    "install_package": (
        "first line: `pip` or `npm`. Second line: the package name alone (optionally pinned, "
        'e.g. `homeharvest==0.8.18`), or a JSON object like {"spec": "homeharvest", '
        '"reason": "real listing data", "allow_new": false}. A URL, path or VCS ref is refused.'
    ),
    "run_script": (
        "every line after the marker is the Python program, and nothing else. It runs with the "
        "repo importable and the network reachable, so `import <an installed library>` works -- "
        "but writing your own network calls (requests, urllib, socket) is still refused: install "
        "a library and call it instead."
    ),
    "browse_page": (
        "first line: the URL or repo path. Second line: a JSON array of actions, e.g. "
        '[{"type": ["#q", "hello"]}, {"click": "#go"}, {"wait": "#results"}, '
        '{"screenshot": "after"}]. Allowed: click, type, press, wait, scroll, screenshot. '
        "There is deliberately no way to run your own JavaScript here."
    ),
    "notify": (
        "first line: a short subject, one line. Every following line: the message body. "
        "This reaches a real person on Slack, email or SMS -- there is no unsend, so write "
        "it as if it will be read by someone who was not watching. Say what happened and "
        "what (if anything) needs them; do not send a routine progress note. Example:\n"
        "NOTIFY: benchmark regressed\nGAIA dropped from 41% to 29% on commit 4f24467.\n"
    ),
    "run_container": (
        "first line: the image (e.g. `python:3.12-slim`). Second line: a JSON object like "
        '{"command": ["python", "-c", "print(1)"], "network": false, '
        '"input_files": ["docs/data.csv"]}. The repo is NOT visible inside -- name files in '
        "input_files and they are copied to /work."
    ),
})
# Tools whose marker takes no argument at all.
_MARKER_NO_ARGS = frozenset({"git_revert"})
# Two-part markers whose SECOND part is a JSON object of extra arguments,
# merged into `args`, rather than one more string.
#
# A single-string marker can only ever carry one meaningful value, so a
# tool with real options had nowhere to put them. Live-caught 2026-09-09
# (second 95120 trial): the model wrote `SEARCH_LISTINGS: San Jose, CA
# 95120 for sale, price filter 1000000 to 4000000, single family` -- the
# whole sentence became `location`, the source matched nothing, and two
# steps were spent on zero results. Now the first line is the one
# required argument and the rest is `{"zip_code": "95120", ...}`.
#
# Degrading gracefully matters more than strictness here: a rest that is
# not valid JSON is kept as the plain second string (the tool's own
# schema then rejects it honestly), and an empty rest adds nothing at
# all, so a bare one-line marker still works exactly as before.
#
# `browse_page` and `run_container` document exactly this same "first
# line plus a JSON second part" shape (see their `_MARKER_ARG_HINT`
# entries) but were missing from this set -- live-caught 2026-09-09
# (tools audit): a `BROWSE_PAGE:` marker whose second line was the
# documented JSON array of actions arrived at the tool as that array's
# *string* rendering, so `render.py::classify_actions` always answered
# "refused: actions must be a list", and a `RUN_CONTAINER:` marker's
# JSON object arrived as the literal text of the `command` field, which
# `shlex.split` then chopped into garbage tokens -- both had never once
# worked from the model's side, exactly the failure mode this set exists
# to prevent for `search_listings`/`install_package`.
_MARKER_JSON_REST = frozenset({"search_listings", "install_package", "browse_page", "run_container"})


def _json_rest(rest: str, second: str) -> dict:
    stripped = (rest or "").strip()
    if not stripped:
        return {}
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            # An object's keys merge straight into `args` -- the
            # `search_listings`/`install_package`/`run_container` shape,
            # where the second part carries several named options.
            return parsed
        if isinstance(parsed, list):
            # `browse_page`'s `actions` IS a JSON array, not a dict of
            # extra options -- assign it to the one field it belongs to
            # rather than trying (and failing) to merge a list.
            return {second: parsed}
    return {second: rest}

# Filled at runtime from Execution's `tool.registered` announcements
# (`orchestration/service.py::_on_tool_registered`) -- MCP servers,
# acquired skills, and open-source adapters (`execution/external.py`)
# become routable without a hand edit here. A hand-written entry above
# always wins over an announced one, so a human can still pin a stricter
# policy for any tool.
_DYNAMIC_TOOLS: dict[str, str] = {}


# Tools Execution has actually announced (`tool.registered`) in the
# current process, kept apart from `_DYNAMIC_TOOLS` above: that one is
# the *policy* table, which unit tests fill directly with made-up names,
# and using it as "what exists" made every later harness test offer the
# model nothing (full-suite-only failures, 2026-09-07). The Orchestration
# service fills this on each announcement and empties it when it stops,
# so one kernel's tools never leak into the next.
_REGISTERED: set[str] = set()


def is_read_only(tool: str) -> bool:
    """Whether `tool` is tagged `read_only` in the policy table --
    `web_fetch`/`web_search`/`read_file`/... never report a
    `file_write`/`file_create` side effect, so a session waiting on one
    has nothing in `session.uncommitted` at stake and can safely stop
    waiting the moment a cancel arrives, rather than riding out the
    tool's own (up to 330s) timeout regardless. An unrecognized name
    defaults to `irreversible` here too, same as `to_action_payload`."""
    return _TOOL_POLICY.get(tool, ("irreversible", False))[0] == "read_only"


def known_tools() -> frozenset[str]:
    """Every tool Execution has announced this process. Empty until the
    first `tool.registered` -- a harness with no Execution -- and then a
    session offers the model only the intersection of its profile and
    this: a profile named `run_shell` while Execution had it switched
    off, and the model was told about a tool that answered "unknown
    tool" (watched trial, 2026-09-07)."""
    return frozenset(_REGISTERED)


def note_registered(name: str) -> None:
    if name:
        _REGISTERED.add(name)


def forget_registered() -> None:
    _REGISTERED.clear()


def offered_tools(profile_tools: tuple[str, ...]) -> tuple[str, ...]:
    """The profile's tools, minus any Execution has not registered, plus
    every skill it HAS registered.

    A profile is a static tuple, so a `skill:<name>` could never appear
    in one -- which meant a skill Sim wrote could not be offered even
    after it was registered (audit, 2026-09-08). Skills are the one tool
    class the system creates for itself; they have to arrive this way."""
    known = known_tools()
    # Intersecting with `known` was a trap waiting to spring. It is
    # empty at boot (Execution announces before Orchestration is
    # listening), and the `if not known` guard hid that by offering the
    # whole profile. The moment ANY single tool registered -- one skill,
    # one slow MCP server -- the intersection would drop every builtin
    # from every later session, leaving a patch session with no
    # read_file (observer, 2026-09-08). A profile names the tools that
    # session should have; registration adds skills to it, and must
    # never subtract.
    offered = list(profile_tools)
    offered.extend(sorted(t for t in known if t.startswith("skill:")))
    return tuple(offered)


def register_tool_policy(name: str, *, reversibility: str, provider: str,
                          marker_arg_key: str | None = None) -> None:
    if not name:
        return
    _DYNAMIC_TOOLS[name] = provider
    if name not in _TOOL_POLICY:
        _TOOL_POLICY[name] = (reversibility, provider in ("mcp", "external"))
    if marker_arg_key:
        # `execution/tools.py::SkillTool` now inspects the skill's own
        # `run()` signature (AST, no exec) and announces its real first
        # parameter name on `tool.registered`. Always wins over whatever
        # is already recorded -- live-caught, audit 2026-09-08: a skill
        # is first announced from disk (no source read yet, so no key)
        # and only gets a real `marker_arg_key` once `_load_skill` reads
        # its source, so the *later*, informed event has to be able to
        # overwrite the earlier default, not be blocked by an
        # already-present entry.
        _MARKER_ARG_KEY[name] = marker_arg_key
    elif name not in _MARKER_ARG_KEY and provider == "skill":
        # No signature info yet (e.g. announced-from-disk, not yet
        # loaded) -- fall back to the historical convention (one string
        # argument named `text`) so a marker call still has a chance of
        # matching a skill whose `run()` genuinely takes `text`, instead
        # of hard-failing with `argument=`.
        _MARKER_ARG_KEY[name] = "text"
    if name not in _MARKER_ARG_KEY and provider == "external":
        # `execution/external.py` wraps every adapter behind one string
        # argument named `input` -- the shape LangChain's own `run(tool_input)`
        # already uses -- so the marker layer needs no per-tool schema.
        _MARKER_ARG_KEY[name] = "input"


def marker_hint(tool: str) -> str | None:
    return _MARKER_ARG_HINT.get(tool)


_FENCE_OPEN = re.compile(r"^\s*```[A-Za-z0-9_+-]*\s*\n")
_FENCE_CLOSE = re.compile(r"\n\s*```\s*$")


def _strip_code_fence(code: str) -> str:
    """Take a markdown fence off a file body before it is written.

    Live-caught 2026-09-07, asking Sim for its first skill: it replied
    with its code wrapped in ```python ... ```, and `apply_skill` wrote
    the fence into the file, so `simorgh_skills/word_count.py` began with
    a literal "```python" and was not valid Python at all.

    Models fence code; that is what they are trained to do, and the
    parser already has `extract_code` for exactly this, used only on the
    `draft_candidate` path. A file body is the one place a stray fence
    turns a working answer into a broken file, so it is stripped here,
    where the body becomes a real write.
    """
    stripped = code.strip("\n")
    if not _FENCE_OPEN.search(stripped):
        return code
    stripped = _FENCE_OPEN.sub("", stripped, count=1)
    return _FENCE_CLOSE.sub("", stripped, count=1)


def to_action_payload(*, action_id: str, task_id: str, call: dict, rationale: str,
                      proposed_by: str = "orchestration") -> dict:
    tool = call.get("tool", "")
    args = call.get("args", {})
    if isinstance(args, dict) and set(args) == {"argument"}:
        raw = args["argument"]
        if tool in ("run_python_sandboxed", "run_js_sandboxed", "run_script"):
            # Same defence the file writers get: a fenced program is still
            # a program. Found by trial 2026-09-07 -- the fence was kept
            # here and stripped for apply_source_patch, so the sandbox
            # failed with a SyntaxError on "```python" every time.
            raw = _strip_code_fence(str(raw))
        if tool in _MARKER_SPLIT_FIRST_LINE:
            first, second = _MARKER_SPLIT_FIRST_LINE[tool]
            head, _, rest = str(raw).partition("\n")
            if second == "code":
                rest = _strip_code_fence(rest)
            args = {first: head.strip(), second: rest}
            if tool in _MARKER_JSON_REST:
                args = {first: head.strip(), **_json_rest(rest, second)}
        elif tool in _MARKER_NO_ARGS:
            args = {}
        elif tool in _MARKER_ARG_KEY:
            args = {_MARKER_ARG_KEY[tool]: raw}
    reversibility, network = _TOOL_POLICY.get(tool, ("irreversible", False))
    paths = [args["path"]] if isinstance(args, dict) and "path" in args else []
    return {
        "action_id": action_id,
        "task_id": task_id,
        "tool": tool,
        "args": args if isinstance(args, dict) else {},
        "scope": {"paths": paths, "network": network},
        "reversibility": reversibility,
        "rationale": rationale,
        # 16-orchestration.md section 3.2: `proposed_by:"orchestration@wN"`
        # -- which Worker proposed it, not just which subsystem. The
        # caller passes its own bound `bus.source`; the default here only
        # covers a caller that never had one (e.g. an ad hoc unit test).
        "proposed_by": proposed_by,
    }
