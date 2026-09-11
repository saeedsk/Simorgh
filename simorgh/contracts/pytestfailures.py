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
#
# `(.+?)`, not `(\S+?)`: a parametrized node id may contain SPACES --
# `test_p[hello world]` is what pytest prints for
# `@pytest.mark.parametrize("x", ["hello world"])`. Against `\S+?` that
# line matched NOTHING at all (the optional ` - <reason>` tail cannot
# start mid-token, so the whole alternation failed), so the failure was
# silently absent from the marker while the ones beside it were listed
# -- a list that read back as complete and was not. Observed here
# 2026-09-10: three failures, a marker naming two.
_SUMMARY_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(.+?)(?:\s+-\s.*)?$", re.MULTILINE)

# pytest's last line: "3 failed in 0.02s", "= 3 failed, 2 passed in
# 1.2s =", "1 failed, 1 error in 0.5s". The authority on HOW MANY
# failed -- see `reported_failures`.
_TAIL = re.compile(r"\bin\s[\d.]+s")
_COUNT = re.compile(r"(\d+)\s+(failed|error|errors)\b")


#: SGR colour and the other CSI sequences a terminal-facing test runner
#: prints when its config forces colour (`--color=yes`, a project's
#: `addopts`) -- which several SWE-bench images do.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(output: str) -> str:
    """`output` with terminal escapes removed.

    `\x1b[32mPASSED\x1b[0m a/b.py::\x1b[1mtest_x\x1b[0m` is what a coloured
    run prints, and every pattern that reads a pytest log expects
    `PASSED a/b.py::test_x`. A whole passing run parsed to NOTHING that
    way and was scored "the suite most likely never ran" -- a real
    SWE-bench fix recorded as unmeasurable (2026-09-10). Here rather than
    in the benchmark, because `run_tests` inside a container prints the
    same escapes and its marker is parsed from the same lines.
    """
    return _ANSI.sub("", output or "")


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


def reported_failures(output: str) -> int | None:
    """How many tests pytest itself says failed, or None if it did not say.

    The count comes from pytest's own tail line rather than from how
    many summary lines were parsed, because those are two different
    numbers whenever a node id does not survive parsing -- and the
    difference is exactly what makes a short list dangerous. A reader
    handed `[failed 2: a b]` when three tests failed will conclude that
    the third one's redness belongs to somebody else. Passing this into
    `format_marker` turns that case into "unattributable", which is the
    only honest reading of a list that is missing something.
    """
    for line in reversed((output or "").strip().splitlines()):
        line = line.strip().strip("=").strip()
        if not line or not _TAIL.search(line):
            continue
        return sum(int(m.group(1)) for m in _COUNT.finditer(line))
    return None


def marker_for(output: str) -> str:
    """The marker for one pytest run's whole output.

    The one entry point a caller with the complete stdout should use: it
    reconciles the ids it could parse against the number pytest itself
    reported, so a run whose summary contains a line this module cannot
    read emits a marker that says "unattributable" rather than a shorter
    list that reads as complete.

    Lines, not unique ids, are what the count is compared against. One
    test can print two summary lines (a failure plus an error in its own
    teardown) and pytest counts both; deduping those to one id is
    correct and must not be mistaken for a lost one.
    """
    ids = failing_nodeids(output)
    if not ids:
        return ""
    reported = reported_failures(output)
    lines = sum(1 for m in _SUMMARY_LINE.finditer(output or "")
                if m.group(1).strip() and not m.group(1).strip().startswith("-"))
    return format_marker(ids, reported if reported is not None and reported != lines else None)


def format_marker(nodeids: tuple[str, ...], total: int | None = None) -> str:
    """The head line for a failing run, or "" when nothing was parsed.

    An empty result means pytest failed without naming a single node id
    (a crash, a usage error, an internal error). That is exactly the
    case a reader must treat as unattributable, and the honest way to
    say it is to emit no marker at all.

    `total` is pytest's own failure count (`reported_failures`) when the
    caller has the whole output to read it from. It is what the marker
    claims, so a list that lost an id -- one whose text this module
    could not parse -- reads back as unattributable rather than as a
    complete, shorter truth. Omitted, the count falls back to the number
    of ids, which is what every caller before this parameter existed
    meant by it.
    """
    if not nodeids:
        return ""
    shown = nodeids[:_MAX_IDS]
    return f"{_PREFIX}{len(nodeids) if total is None else total}: {' '.join(shown)}]"


def _marker_span(text: str) -> tuple[int, int] | None:
    """`(start, end)` of the marker, `end` being its closing bracket.

    The marker ends at the LAST `]` on its own line, not the first.
    Almost every real node id ends in one -- `test_p[plain]` is what
    pytest prints for any parametrized test -- so a first-`]` scan cut
    `[failed 2: tests/x.py::test_p[plain] tests/x.py::test_y]` down to
    `2: tests/x.py::test_p[plain`, whose one id did not match the count
    and so read back as None. Attribution therefore switched itself off
    whenever a parametrized test was among the failures, which in this
    suite is most of the time, and the red-suite budget burn it was
    written to stop came straight back (observer, 2026-09-10).
    """
    start = (text or "").find(_PREFIX)
    if start < 0:
        return None
    line_end = text.find("\n", start)
    line = text[start:line_end if line_end >= 0 else len(text)]
    end = line.rfind("]")
    if end < 0:
        return None
    return start, start + end


def parse_marker(text: str) -> tuple[str, ...] | None:
    """The complete list of failing node ids, or None.

    None means "this run's failures are not known here" -- no marker, a
    marker written before this existed, or a marker whose list was
    capped and so is not the whole truth. Every caller must treat None
    as "cannot attribute", never as "nothing failed".
    """
    span = _marker_span(text)
    if span is None:
        return None
    start, end = span
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
    span = _marker_span(text)
    if span is None:
        return text
    start, end = span
    marker = text[start:end + 1]
    rest = (text[:start] + text[end + 1:]).lstrip("\n")
    return f"{marker}\n{rest}"
