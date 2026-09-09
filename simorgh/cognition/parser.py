"""Output parsing: markers, edit blocks, non-answer detection (docs/
blueprint/subsystems/04-cognition.md section 5, "Output parsing"). Ported
directly from v1 `src/cognition/tool_protocol.py` and
`src/orchestrator/self_patch.py` -- every rule below is a real,
live-caught lesson (see docs/EVOLUTION.md), not a fresh design:

- A model doesn't always stop at a marker; it keeps reasoning out loud
  in the same response. For a single-bare-token argument (a path, a
  name), only the first non-empty line was ever the real answer
  (`first_line_argument`). For a code-bearing marker (v1: `DRAFT`/`RUN`;
  v2's markers are the real tool names from `session.profile.tools`
  (`orchestration/profiles.py`), so this is `draft_candidate`/
  `run_python_sandboxed` -- see `_CODE_BEARING_MARKERS` below), everything
  after the marker is the payload, kept intact.
- A "verdict" response (`YES`/`NO`) can be silently non-compliant: the
  model narrates instead of answering. Scanning every line for a
  standalone YES/NO, and reporting `non_answer=True` when none is found,
  turns a would-be false rejection into an honest "the reviewer didn't
  review" signal the caller can defer on, never a rejection.
- SEARCH/REPLACE blocks use the exact three-way conflict-marker shape
  (`<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE`) real merge conflicts
  and tools like Aider already use -- a shape the model has seen
  thousands of times, not a bespoke format.
"""

from __future__ import annotations

import ast
import re

from .api import ParsedOutput

_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)
_YES_NO_RE = re.compile(r"\b(YES|NO)\b", re.IGNORECASE)
_EDIT_BLOCK_RE = re.compile(
    r"<<<<<<< SEARCH\n(?P<old>.*?)\n=======\n(?P<new>.*?)\n>>>>>>> REPLACE", re.DOTALL,
)
_DEFAULT_PREVIEW_LIMIT = 150
# v2's real markers are the tool names from `session.profile.tools`
# (`orchestration/profiles.py`), so this has to name `draft_candidate`/
# `run_python_sandboxed`, not v1's short `DRAFT`/`RUN` -- kept alongside
# the v1 names since callers (including this module's own tests) are
# free to configure any marker vocabulary, and a code-bearing tool
# should keep its full payload under either naming scheme.
_CODE_BEARING_MARKERS = {
    "DRAFT", "RUN", "DRAFT_CANDIDATE", "RUN_PYTHON_SANDBOXED",
    # Multi-line payloads whose first line is a path and the rest is the
    # complete file body (`orchestration/tools.py::_MARKER_SPLIT_FIRST_LINE`).
    "APPLY_SOURCE_PATCH", "APPLY_SKILL",
    # `git_commit` is the same shape: first line the path, the rest the
    # commit message. Without it here the message was cut off and the
    # commit went out empty -- live-caught 2026-09-07, watching Sim write
    # its first real file and then fail to commit it three times running,
    # each with `args={'message': '', 'path': 'simorgh/greeting.py'}`.
    "GIT_COMMIT",
    # `propose_mcp_server` is told, in its own marker hint, to write
    # `key: value` lines one per line -- and then had everything but the
    # first line thrown away, so `command` was always empty and every
    # call answered "'command' must be one of [...], got ''". The model
    # wrote the documented form six times in a row and burned a whole
    # chat budget on it.
    "PROPOSE_MCP_SERVER",
    # A shell command is routinely multi-line: a heredoc, or two
    # commands joined by a newline. Truncating to the first line turned
    # `python3 - <<'EOF' ...` into a program with empty stdin, which
    # exits 0 with no output -- so the model was told its edit had been
    # applied when nothing had run at all.
    "RUN_SHELL",
    # Same defect, live-caught by an observer trial 2026-09-09 running
    # the brand-new resourcefulness toolset for the first time: each of
    # these four is a two-field marker split by
    # `orchestration/tools.py::_MARKER_SPLIT_FIRST_LINE` (image/command,
    # location/filters, target/actions, manager/spec) -- but none of them
    # were listed here, so `first_line_argument` threw away everything
    # after line 1 before that split ever ran. Every `RUN_CONTAINER:
    # <image>\n<command>` call arrived with `command` silently missing,
    # no matter how the model formatted it; a trial burned its entire
    # step budget on `run_container` for exactly this reason, never once
    # discovering that the tool was reachable, and only stumbled onto
    # a working call when a single JSON line happened to keep both
    # fields on one line by accident. `search_listings`, `browse_page`
    # and `install_package` have the identical shape and the identical
    # defect.
    "RUN_CONTAINER", "SEARCH_LISTINGS", "BROWSE_PAGE", "INSTALL_PACKAGE",
    # Same shape again (kind/spec), on the grants branch. Listed here
    # so that branch does not inherit the identical defect the moment
    # it merges -- an unregistered marker costs nothing.
    "GRANT_CAPABILITY",
    # Same class of tool as `run_python_sandboxed` just above (the whole
    # payload after the marker is the program) but added on a different
    # day and left off this set -- same live-caught defect: only the
    # first line of the script ever reached the tool.
    "RUN_SCRIPT",
}


def preview(text: str, limit: int = _DEFAULT_PREVIEW_LIMIT) -> str:
    """A bounded, single-line-safe preview for narration/telemetry --
    never the value used for real work."""
    collapsed = text.replace("\r\n", " ").replace("\n", " ⏎ ").strip()
    if len(collapsed) > limit:
        return collapsed[:limit] + f"… (+{len(collapsed) - limit} more chars)"
    return collapsed


def first_line_argument(text: str) -> str:
    """The first non-empty line, stripped -- for an argument that's
    always exactly one bare token (a path, a name), never free-form
    prose the model may have kept generating past the marker."""
    stripped = text.strip()
    return stripped.splitlines()[0].strip() if stripped else ""


# A model's own tool-call syntax, leaking through the marker convention.
_NATIVE_TOOL_TAG = re.compile(r"</?(?:tool_call|tool_calls|function_call|arg_key|arg_value|parameter)>")


def _unwrap_native_tool_tags(text: str) -> str:
    """Put a marker back on its own line when the model wrapped it in the
    tool-call syntax it was trained on.

    Live-caught 2026-09-07, asking Sim for a skill. GLM-5.3-Flash replied
    "I'll start by checking whether the skill already exists.<tool_call>
    SEARCH_CODE: word_count</arg_value>..." -- a real call, in the
    provider's own format, with our marker inside the tag and therefore
    invisible to a line scan. The session recorded a final answer and the
    task "completed" having done nothing.

    Turning the tags into line breaks is enough to see the call, and
    leaves anything that is genuinely prose alone.
    """
    return _NATIVE_TOOL_TAG.sub("\n", text)


def count_markers(text: str, markers: tuple[str, ...]) -> int:
    """How many lines in `text` are tool markers.

    Only the first is ever executed (one action per step, 16 section 7).
    Knowing there were others is what lets the session say so instead of
    dropping them in silence."""
    stripped = _unwrap_native_tool_tags(text).strip()
    prefixes = tuple(f"{m}:".upper() for m in markers)
    return sum(1 for line in stripped.splitlines() if line.strip().upper().startswith(prefixes))


def parse_marker(text: str, markers: tuple[str, ...]) -> tuple[str | None, str]:
    """Find a tool call in `text`. Returns (marker.lower(), payload), or
    (None, text) meaning "final answer, no tool call".

    A marker at the very start is the documented form and is preferred.
    Failing that, the first line that *begins* with a marker counts too.

    That fallback is not laxity, it is the difference between Sim editing
    its own source and not. Live-caught 2026-09-07: asked to add a
    docstring, the model read the right file and then replied "Let me get
    my bearings before continuing.\nSEARCH_CODE: ...". One sentence of
    preamble, and the call was invisible -- the reply was filed as a
    final answer, the task "completed", and nothing was written. Across
    the whole ledger that pattern accounts for 246 tool runs without a
    single `apply_source_patch`. The instruction does say "nothing before
    it"; a model that adds a polite line first is still unambiguously
    asking for a tool, and refusing to hear it helps nobody.

    A marker must own its line: a mention inside a sentence stays prose.
    """
    stripped = _unwrap_native_tool_tags(text).strip()
    for marker in markers:
        prefix = f"{marker}:"
        if stripped[: len(prefix)].upper() == prefix.upper():
            return marker.lower(), stripped[len(prefix):].strip()

    lines = stripped.splitlines()
    for index, line in enumerate(lines):
        candidate = line.strip()
        for marker in markers:
            prefix = f"{marker}:"
            if candidate[: len(prefix)].upper() != prefix.upper():
                continue
            rest = candidate[len(prefix):].strip()
            tail = "\n".join(lines[index + 1:]).strip()
            return marker.lower(), f"{rest}\n{tail}".strip() if tail else rest
    return None, stripped


def extract_code(text: str) -> str | None:
    match = _CODE_FENCE.search(text)
    stripped = (match.group(1) if match else text).strip()
    return stripped or None


def is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def parse_search_replace_blocks(text: str) -> list[tuple[str, str]] | None:
    """(old, new) pairs, or None if the text contains no recognizable
    block at all -- distinct from an empty list, which never happens.
    None is the signal the caller uses to fall back to treating `text`
    as a plain full-file/final answer instead: a model that ignores the
    edit-block instruction and answers directly is still a working
    answer, not an error.
    """
    matches = [(m.group("old"), m.group("new")) for m in _EDIT_BLOCK_RE.finditer(text)]
    return matches or None


def scan_verdict(text: str) -> bool | None:
    """The first standalone YES/NO found on any line, or None if the
    response never states one -- a non-answer, not a rejection."""
    for line in text.strip().splitlines():
        match = _YES_NO_RE.search(line.strip())
        if match is not None:
            return match.group(1).upper() == "YES"
    return None


class OutputParser:
    """Parses a provider's raw text according to `expected` (04 section
    3.4's `OutputSpec`): `{kind: final|markers|edit_blocks|verdict, markers?: [...]}`.
    """

    def parse(self, text: str, expected: dict | None) -> ParsedOutput:
        expected = expected or {"kind": "final"}
        kind = expected.get("kind", "final")
        if kind == "markers":
            return self._parse_markers(text, tuple(expected.get("markers", ())))
        if kind == "edit_blocks":
            return self._parse_edit_blocks(text)
        if kind == "verdict":
            return self._parse_verdict(text)
        return ParsedOutput(kind="final", text=text.strip())

    def _parse_markers(self, text: str, markers: tuple[str, ...]) -> ParsedOutput:
        marker, payload = parse_marker(text, markers)
        if marker is None:
            return ParsedOutput(kind="final", text=payload)
        # Multi-line-payload markers (code-bearing) keep the payload intact;
        # single-token markers use only the first line (the live-caught
        # lesson). Live-caught a second time: this used to check
        # `marker.upper() in {"DRAFT", "RUN"}` -- v1's short marker names,
        # which never match v2's real markers (`session.profile.tools`'
        # full tool names, e.g. `draft_candidate`/`run_python_sandboxed`),
        # so every code-bearing call silently lost everything past its
        # first line.
        arg = payload if marker.upper() in _CODE_BEARING_MARKERS else first_line_argument(payload)
        # One action per step is deliberate (16 section 7), but the extra
        # markers used to vanish without trace: a reply carrying
        # SEARCH_CODE + WEB_SEARCH ran only the first, so a whole half of
        # a task never happened and nothing said so. Count them, so the
        # session can tell the model what it dropped (observer round,
        # 2026-09-08 -- three observers hit this independently).
        call = {"tool": marker, "args": {"argument": arg}}
        extra = count_markers(text, markers) - 1
        if extra > 0:
            # Only when it means something, so an ordinary call keeps its
            # minimal shape on the wire.
            call["dropped_markers"] = extra
        return ParsedOutput(kind="tool_calls", text=text.strip(), tool_calls=(call,))

    def _parse_edit_blocks(self, text: str) -> ParsedOutput:
        blocks = parse_search_replace_blocks(text)
        if blocks is None:
            candidate = extract_code(text)
            return ParsedOutput(kind="final", text=candidate or text.strip())
        return ParsedOutput(
            kind="edit_blocks", text=text.strip(),
            edit_blocks=tuple({"search": old, "replace": new} for old, new in blocks),
        )

    def _parse_verdict(self, text: str) -> ParsedOutput:
        verdict = scan_verdict(text)
        if verdict is None:
            return ParsedOutput(kind="non_answer", text=text.strip(), non_answer=True)
        return ParsedOutput(kind="verdict", text=text.strip(), verdict=verdict)


__all__ = [
    "OutputParser", "extract_code", "first_line_argument", "is_valid_python",
    "parse_marker", "parse_search_replace_blocks", "preview", "scan_verdict",
]
