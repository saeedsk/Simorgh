"""How one line of text becomes a tool call's arguments.

The model writes `KB_SEARCH: flood cover` and means
`{"query": "flood cover"}`. A person types `tool kb_search flood cover`
and means exactly the same thing. Both need the same table, and until
this module existed only Orchestration had it -- so the `tool` command
either duplicated it (and drifted) or made a person write JSON for
something the model gets for free.

That table is a contract in the strict sense: it is the agreed shape of
a tool call, and two subsystems that disagree about it produce calls the
tool cannot read. `contracts` is where such agreements live, and this
one is stdlib-only like the rest.

The model-facing *prose* -- the hints that tell the model what to put on
each line -- stays in Orchestration. That is prompt text, not a shape.
"""

from __future__ import annotations

import json
import re

#: Tools whose whole argument is one string: `{"query": "..."}`. The
#: key is what that string is called.
#:
#: Mutable on purpose: Orchestration adds a row here at runtime for
#: every single-argument MCP tool a server announces
#: (`orchestration/service.py::_on_tool_registered`), so the CLI's
#: `tool` command understands those too without a second mechanism.
MARKER_ARG_KEY: dict[str, str] = {
    # The TV (execution/media/cast.py). One line of text each; the tool
    # reads the rest of the line -- `<url> full`, `35 Bedroom` -- itself.
    # Without these rows every spoken "cast it" arrived as no arguments
    # and was refused three times in a row (the creator, 2026-09-12).
    # The cameras (execution/home/cameras.py): one line, the camera's
    # name first and the rest of the line read by the tool.
    "cam_state": "camera", "cam_snapshot": "camera", "cam_stream": "camera", "cam_light": "camera",
    "cam_ir": "camera", "cam_siren": "camera", "cam_ptz": "camera", "cam_recordings": "camera",
    "cam_watch": "on",
    "ring_snapshot": "camera", "ring_events": "camera", "ring_light": "camera", "ring_siren": "camera", "ring_watch": "on",
    "cast_play": "url",
    "cast_show": "target",
    "cast_stop": "what",
    "cast_volume": "level",
    "dash_view": "view",
    "cast_use": "device",
    "cast_setup": "device",
    "energy_report": "range",
    "media_now": "where",
    "home_find": "query",
    "home_state": "target",
    "home_describe": "query",
    "sec_show": "finding",
    "cal_list": "range",
    "mail_search": "query",
    "mail_read": "message",
    "kb_search": "query",
    "kb_ask": "question",
    "kb_open": "citation",
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

#: Tools that take no arguments at all. A stray empty-string argument
#: fails schema validation, so these must send `{}` rather than
#: `{"": ""}` or `{"argument": ""}`.
MARKER_NO_ARGS: frozenset[str] = frozenset({
    "git_revert", "kb_status", "sec_self", "sec_posture", "energy_status", "cast_devices", "cam_list",
})

#: Tools whose argument is two parts: the first line, then everything
#: after it. `("subject", "body")` means line one is the subject.
MARKER_SPLIT_FIRST_LINE: dict[str, tuple[str, str]] = {
    "cam_setup": ("host", "spec"),
    "apply_source_patch": ("subject", "code"),
    "replace_in_file": ("path", "code"),
    "start_task": ("goal", "spec"),
    "apply_skill": ("subject", "code"),
    "git_commit": ("path", "message"),
    "search_listings": ("location", "filters"),
    "browse_page": ("target", "actions"),
    "run_container": ("image", "command"),
    "install_package": ("manager", "spec"),
    "notify": ("subject", "body"),
    "kb_sources": ("op", "spec"),
    "remind": ("when", "text"),
    "sec_accept": ("finding", "reason"),
    "sec_findings": ("severity", "spec"),
    "home_call": ("service", "spec"),
    "home_undo": ("entity", "spec"),
    "energy_tariff": ("op", "spec"),
    "media_control": ("op", "spec"),
    "media_play": ("what", "spec"),
    # The Mac's Music app: same two shapes as the home players.
    "music_control": ("op", "spec"),
    "music_play": ("query", "spec"),
}

#: Of those, the ones whose second part is JSON whose keys merge into
#: the arguments. Live-caught twice: a marker whose second line was the
#: documented JSON arrived at the tool as that JSON's *string*
#: rendering, and the tool had never once worked from the model's side.
MARKER_JSON_REST: frozenset[str] = frozenset({
    "start_task", "cam_setup",
    "search_listings", "install_package", "browse_page", "run_container",
    "kb_sources", "sec_findings", "home_call", "home_undo",
    "energy_tariff", "media_control", "media_play",
    "music_control", "music_play",
})

#: Tools whose second part is a program, so a markdown fence around it
#: has to come off before it is written or run.
MARKER_CODE_REST: frozenset[str] = frozenset({"apply_source_patch", "apply_skill",
                                              "replace_in_file"})


_FENCE_OPEN = re.compile(r"^\s*```[A-Za-z0-9_+-]*\s*\n")
_FENCE_CLOSE = re.compile(r"\n\s*```\s*$")


def strip_code_fence(code: str) -> str:
    """Take a markdown fence off a body before it is written or run.

    Live-caught 2026-09-07, asking Sim for its first skill: it replied
    with its code wrapped in a fence, `apply_skill` wrote the fence into
    the file, and `simorgh_skills/word_count.py` began with a literal
    "```python" and was not valid Python at all. Models fence code; that
    is what they are trained to do, and a file body is the one place a
    stray fence turns a working answer into a broken file.
    """
    stripped = (code or "").strip("\n")
    if not _FENCE_OPEN.search(stripped):
        return code
    stripped = _FENCE_OPEN.sub("", stripped, count=1)
    return _FENCE_CLOSE.sub("", stripped, count=1)


def json_rest(rest: str, second: str) -> dict:
    """The second part of a two-part marker, as arguments."""
    stripped = (rest or "").strip()
    if not stripped:
        return {}
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            # `raw_decode`, not `loads`: a model routinely closes with a
            # sentence after its JSON --
            #     HOME_CALL: light.turn_on
            #     {"entity_id": "light.kitchen"}
            #     That should do it.
            # -- and `loads` raised on the trailing line, so the whole
            # second part fell through to the raw-text branch and
            # `home_call` reached its tool with a service and no target.
            # That is the same silent failure the marker-truncation fix
            # ended this morning, reached by a different reply shape
            # (observer, 2026-09-10). The narration after the value is
            # dropped, which is what it is.
            parsed, _end = json.JSONDecoder().raw_decode(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            # An object's keys merge straight into the arguments.
            return parsed
        if isinstance(parsed, list):
            # `browse_page`'s `actions` IS a JSON array, not a dict of
            # extra options -- assign it to the one field it belongs to
            # rather than trying (and failing) to merge a list.
            return {second: parsed}
    return {second: rest}


def args_from_text(tool: str, raw: str) -> dict:
    """One block of text as a tool's arguments.

    This is the whole of what `KB_SEARCH: flood cover` means, and it is
    also what `tool kb_search flood cover` should mean. A tool with no
    entry in any table gets `{}` rather than a guess: inventing an
    argument name produces a call the tool silently ignores, which is
    harder to diagnose than one that plainly had no arguments.
    """
    raw = raw if raw is not None else ""
    if tool in MARKER_NO_ARGS:
        return {}
    if tool in MARKER_SPLIT_FIRST_LINE:
        first, second = MARKER_SPLIT_FIRST_LINE[tool]
        head, _, rest = str(raw).partition("\n")
        if tool in MARKER_CODE_REST:
            rest = strip_code_fence(rest)
        if tool in MARKER_JSON_REST:
            return {first: head.strip(), **json_rest(rest, second)}
        return {first: head.strip(), second: rest}
    if tool in MARKER_ARG_KEY:
        if tool in ("run_python_sandboxed", "run_js_sandboxed", "run_script"):
            raw = strip_code_fence(str(raw))
        return {MARKER_ARG_KEY[tool]: raw}
    return {}


def describe_arguments(tool: str) -> str:
    """What to type after a tool's name, in one line, for a person."""
    if tool in MARKER_NO_ARGS:
        return "(no arguments)"
    if tool in MARKER_SPLIT_FIRST_LINE:
        first, second = MARKER_SPLIT_FIRST_LINE[tool]
        if tool in MARKER_JSON_REST:
            return f"<{first}> then a JSON object of options on the next line"
        return f"<{first}> then <{second}> on the following lines"
    if tool in MARKER_ARG_KEY:
        return f"<{MARKER_ARG_KEY[tool]}>"
    return "key=value pairs, or a JSON object"


__all__ = ["MARKER_ARG_KEY", "MARKER_CODE_REST", "MARKER_JSON_REST", "MARKER_NO_ARGS",
           "MARKER_SPLIT_FIRST_LINE", "args_from_text", "describe_arguments", "json_rest",
           "strip_code_fence"]
