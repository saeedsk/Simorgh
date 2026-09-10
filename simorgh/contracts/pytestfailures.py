"""Which tests failed, in a form that survives truncation.

`execution/tools.py::RunTestsTool` returns pytest's own stdout, tail
first (`completed.stdout[-cap:]`), and `orchestration/session.py`
records the step from the HEAD of that (`full[:_DETAIL_CHARS]`, 2000
chars) and shows the model the first 8000. pytest prints its short
summary -- the `FAILED tests/x.py::test_y` lines, the only place the
node ids appear -- at the very END. So for any run whose output is
longer than the cut, neither the model nor a later mechanical check
ever learned WHICH tests failed: both saw a stack trace from the top of
the run and the word "failed".

This module is that missing wire. `RunTestsTool` parses its own output
once, while it still has all of it, and prepends `format_marker(...)`
so the fact rides at the head where nothing truncates it;
`verification/checks/fullsuiteran.py` reads it back with
`parse_marker`.

The marker carries the TOTAL count as well as the ids, so a reader can
tell "these are all of them" from "these are the first few". Only an
exact, complete list is worth anything to a check that has to decide
whether a change is to blame: a partial list is silently unattributable
and must read back as unavailable, never as a short list.
"""

from __future__ import annotations

import re

# One line, at the head of a failing `run_tests` output. `n` is the
# total number of failing/erroring node ids pytest reported; the ids
# that follow are as many as fit under `MAX_IDS`.
_PREFIX = "[failed "
_MAX_IDS = 40

# pytest's short summary lines, both `-q` and `-n auto` (xdist prints
# the same shape). `ERROR tests/x.py` (a collection error) has no
# `::test`, and is still a real failing target worth naming.
_SUMMARY_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s.*)?$", re.MULTILINE)


def failing_nodeids(output: str) -> tuple[str, ...]:
    """Every node id pytest named in its short summary, in order, deduped."""
    found: dict[str, None] = {}
    for match in _SUMMARY_LINE.finditer(output or ""):
        nodeid = match.group(1).strip()
        # Guard against a stray "FAILED" inside a captured stdout block:
        # a real node id is a path, or a path::selector.
        if nodeid and not nodeid.startswith("-"):
            found.setdefault(nodeid, None)
    return tuple(found)


def format_marker(nodeids: tuple[str, ...]) -> str:
    """The head line for a failing run, or "" when nothing was parsed.

    An empty result means pytest failed without naming a single node id
    (a crash, a usage error, an internal error). That is exactly the
    case a reader must treat as unattributable, and the honest way to
    say it is to emit no marker at all.
    """
    if not nodeids:
        return ""
    shown = nodeids[:_MAX_IDS]
    return f"{_PREFIX}{len(nodeids)}: {' '.join(shown)}]"


def parse_marker(text: str) -> tuple[str, ...] | None:
    """The complete list of failing node ids, or None.

    None means "this run's failures are not known here" -- no marker, a
    marker written before this existed, or a marker whose list was
    capped and so is not the whole truth. Every caller must treat None
    as "cannot attribute", never as "nothing failed".
    """
    start = (text or "").find(_PREFIX)
    if start < 0:
        return None
    end = text.find("]", start)
    if end < 0:
        return None
    body = text[start + len(_PREFIX):end]
    count, _, ids = body.partition(":")
    try:
        total = int(count.strip())
    except ValueError:
        return None
    nodeids = tuple(part for part in ids.split() if part)
    if total <= 0 or len(nodeids) != total:
        return None
    return nodeids


def hoist_marker(text: str) -> str:
    """The same text with the failure marker moved to the front.

    Prepending the marker to the tool's own output is not enough on its
    own. `execution/service.py::_publish_result` puts up to 1500
    characters of stderr into the result's `error`, and
    `orchestration/session.py` renders a failed step as
    `f"{error}\n\n{output}"` before cutting it to 2000 -- so a run whose
    stderr is noisy (pytest-asyncio's deprecation banner, once per xdist
    worker) spends three quarters of the step's whole budget before the
    tool's output starts. Measured on a live trial 2026-09-10: the
    marker landed at character 1535 of 2000 and survived by 465
    characters.

    Moving it rather than copying it: the budget this exists to fit
    inside is the same budget a duplicate would eat.
    """
    start = (text or "").find(_PREFIX)
    if start < 0:
        return text
    end = text.find("]", start)
    if end < 0:
        return text
    marker = text[start:end + 1]
    rest = (text[:start] + text[end + 1:]).lstrip("\n")
    return f"{marker}\n{rest}"
