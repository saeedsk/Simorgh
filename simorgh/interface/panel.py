"""The Claude-Code-shaped screen: what goes where, and how it looks.

The creator, 2026-09-07, with a screenshot of Claude Code: the bottom of
the screen lists what is going on right now (running work, its forks,
whether auto mode is on); above that sits the input bar, whose history
the arrow keys scroll; and everything above *that* is the transcript --
the conversation, code diffs coloured by side, each task's tool calls
drawn as a tree with box-drawing lines and how long every call took,
and, while Sim works, a breathing word like "Osmosing…" instead of a
static "thinking".

This module is the pure part: every function here turns state into
text and nothing here touches a terminal, so all of it is testable
without one. `service.py` decides *when* to call these; `tui.py` puts
the bottom rows into the prompt's toolbar and re-renders them on a
timer so the breathing actually breathes.

Layout, bottom to top:

    ┌ transcript ─────────────────────────────────────────────┐
    │ ⏺ patch · human · add a docstring to vitals.py  [a88b70] │
    │   ⏺ read_file(simorgh/interface/vitals.py)     ✓  0.3s   │
    │   ⏺ apply_source_patch(simorgh/interface/vit…) ✓  1.2s   │
    │     ⎿  --- a/simorgh/interface/vitals.py                 │
    │        +\"\"\"A real local projection …\"\"\"                   │
    │        … +14 lines                                       │
    │   ⏺ run_tests(tests/simorgh/interface)         ✓ 42.0s   │
    │   ⎿  ✅ completed in 60s                                  │
    │                                                          │
    │ ● Docstring added and the tests pass.                    │
    │   • vitals.py gained a module docstring                  │
    ├ input ──────────────────────────────────────────────────┤
    │ ❯ _                                                      │
    ├ activity ───────────────────────────────────────────────┤
    │ ✻ Osmosing…  research · what does memory export · 12s    │
    │   ↳ 2 queued: tighten the retry loop; plan web access    │
    │ ⏵⏵ auto on · guarded · GLM-5.3-Flash · together 12/200   │
    └──────────────────────────────────────────────────────────┘

The glyphs are Claude Code's own since 2026-09-12, when the creator
pasted its transcript as "a perfect example of what I'm looking for":
a `⏺` per call, `⎿` for what hangs under it, `●` for an answer, `❯` for
the prompt in light grey, and a diff shown as a short coloured excerpt
with "… +N lines" rather than the whole thing.
"""

from __future__ import annotations

import hashlib
import math

from .activity import TaskBook, TaskRecord

# The words Sim breathes while it thinks. The first four are the
# creator's own ("'Osmosing...' 'dive deeping' 'snargleing...'
# 'Thinkering...'"); the rest keep them company so a long session does
# not repeat itself. Only the gather phase (a model call) gets one --
# a tool call keeps its plain verb ("Reading", "Patching") because
# there the *meaning* matters more than the mood.
BREATH_WORDS: tuple[str, ...] = (
    "Thinkering", "Osmosing", "Snargling", "Dive-deeping",
    "Pondering", "Noodling", "Percolating", "Cogitating", "Mulling",
    "Ruminating", "Tinkering", "Brewing", "Puzzling", "Marinating",
    "Simmering", "Musing", "Wrangling", "Scheming", "Incubating",
    "Untangling", "Distilling", "Composting", "Fermenting", "Dreaming",
)
BREATH_ROTATE_S = 7.0

# Breathing colour: a triangular wave over a handful of shades, so the
# word swells from dim to bright and back. Style classes; the actual
# colours live in `tui.py::_style()` and default to plain text
# anywhere else.
BREATH_SHADES = 6
BREATH_PERIOD_S = 2.4

MAX_RUNNING_ROWS = 3
MAX_QUEUED_NAMED = 2
# Room the fixed parts of each row need; the topic takes the rest of the
# real terminal (`render.terminal_width`).
_ROW_OVERHEAD = 44
_QUEUE_OVERHEAD = 60
_TREE_OVERHEAD = 2


# ----------------------------------------------------------------- breathing
def breath_word(seed: str, elapsed: float, *, rotate_s: float = BREATH_ROTATE_S) -> str:
    """Which word a task is breathing right now. Deterministic in the
    task id, so two REPLs watching the same task agree, and it changes
    every `rotate_s` seconds so a long think is not one frozen word."""
    digest = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16)
    step = int(max(0.0, elapsed) // rotate_s)
    return BREATH_WORDS[(digest + step) % len(BREATH_WORDS)]


def breath_shade(t: float, *, period_s: float = BREATH_PERIOD_S, shades: int = BREATH_SHADES) -> int:
    """0 (dimmest) .. shades-1 (brightest), rising and falling once per
    `period_s`. A sine, not a sawtooth: no snap back to dim."""
    phase = (max(0.0, t) % period_s) / period_s
    level = (1 - math.cos(2 * math.pi * phase)) / 2  # 0 -> 1 -> 0
    return min(shades - 1, int(round(level * (shades - 1))))


def breath_class(t: float) -> str:
    return f"class:sim.breath.{breath_shade(t)}"


# The spark before the word cycles through these, one every
# `SPARK_FRAME_S`: a dot that opens into a star and closes again. The
# creator, 2026-09-12: "the ✻ breathing by changing character between
# · + ✶ ✻".
SPARK_FRAMES: tuple[str, ...] = ("·", "+", "✶", "✻", "✶", "+")
SPARK_FRAME_S = 0.3
# How far along the word the colour wave has travelled per second of
# `WAVE_PERIOD_S`: each letter breathes a little after the one to its
# left, so the brightness rolls left to right and repeats.
WAVE_PERIOD_S = 2.4
WAVE_SPREAD = 0.12  # of a period, per letter


def spark(t: float, *, unicode: bool = True) -> str:
    if not unicode:
        return "*"
    return SPARK_FRAMES[int(max(0.0, t) / SPARK_FRAME_S + 1e-9) % len(SPARK_FRAMES)]


def breathing_word(word: str, t: float, *, unicode: bool = True) -> list[tuple[str, str]]:
    """`word…` as one fragment per letter, each with the breath shade
    for its place in the wave: the leftmost letter brightens first,
    the next a beat later, and so on down the word, over and over."""
    text = f"{word}…" if unicode else f"{word}..."
    out: list[tuple[str, str]] = []
    for i, ch in enumerate(text):
        shade = breath_shade(t - i * WAVE_SPREAD * WAVE_PERIOD_S, period_s=WAVE_PERIOD_S)
        out.append((f"class:sim.breath.{shade}", ch))
    return out


# ------------------------------------------------------------ transcript tree
_OK = {True: "✓", False: "✗"}
_END_ICON = {"completed": "✅", "failed": "❌", "blocked": "⏸", "paused": "⏸"}
_KIND_ICON = {"research": "🔍", "patch": "🔧", "skill": "🎓", "project": "🗂", "chat": "💬"}


def _topic(overhead: int) -> int:
    from .render import terminal_width

    return max(24, terminal_width() - overhead)


def _fit(text: str, width: int) -> str:
    from .render import fit

    return fit(" ".join(text.split()), width)


def _line(text: str) -> str:
    """A finished row, cut to the real terminal in display columns."""
    from .render import fit, terminal_width

    return fit(text, terminal_width())


def _took(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 90:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.1f}m"


def tree_start(record: TaskRecord, *, unicode: bool = True) -> str:
    """The root of a task's tree: kind, who asked, and what it is about."""
    icon = _KIND_ICON.get(record.kind, "•") if unicode else "*"
    head = "⏺" if unicode else "*"
    return _line(f"{head} {icon} {record.kind} · {record.origin} · {record.short_topic()}  [{record.task_id[:8]}]")


def tree_step(*, tool: str | None, head: str, ok: bool | None, took: float | None,
              width: int | None = None, unicode: bool = True) -> str:
    """One tool call: `  ⏺ tool(what)  ✓ 0.3s`.

    Box-drawing rails (`├─`, `╰─`) until 2026-09-12; the creator then
    pasted Claude Code's own transcript as "a perfect example of what
    I'm looking for": a `⏺` per call, with what hangs under it -- output,
    a diff, the outcome -- behind a `⎿`. Same shape here.
    """
    from .render import terminal_width

    width = (terminal_width() - _TREE_OVERHEAD) if width is None else width
    branch = "  ⏺ " if unicode else "  * "
    what = f"{tool}({head})" if tool and head else (tool or head)
    from .render import display_width as _dw

    what = _fit(what, width - _dw(branch) - _dw(f"{_OK.get(ok, '…')} {_took(took)}") - 2)
    mark = _OK.get(ok, "…") if unicode else {True: "ok", False: "FAILED"}.get(ok, "..")
    tail = f"{mark} {_took(took)}".rstrip()
    from .render import display_width

    pad = max(1, width - display_width(branch) - display_width(what) - display_width(tail))
    return _line(f"{branch}{what}{' ' * pad}{tail}")


def tree_note(lines: list[str], *, unicode: bool = True) -> list[str]:
    """Lines that belong *under* a branch -- a diff, a test summary --
    kept inside the tree's rail so the eye can follow it."""
    # A long diff line used to run past the terminal and wrap, breaking
    # the tree's own rail (observer, 2026-09-08). The first line hangs
    # from the call by a `⎿`, the rest sit under it.
    if not lines:
        return []
    first = "    ⎿  " if unicode else "    `- "
    rest = "       "
    return [_line(f"{first}{lines[0]}")] + [_line(f"{rest}{line}") for line in lines[1:]]


def tree_end(record: TaskRecord, *, elapsed: float | None, detail: str = "", unicode: bool = True) -> str:
    icon = _END_ICON.get(record.status, "•") if unicode else ""
    corner = "  ⎿  " if unicode else "  `- "
    took = f" in {_took(elapsed)}" if elapsed is not None else ""
    tail = f" -- {detail}" if detail else ""
    return _line(f"{corner}{icon} {record.status}{took}{tail}")


# ------------------------------------------------- the live section (above the prompt)
def running_row(record: TaskRecord, *, now: float, unicode: bool = True) -> list[tuple[str, str]]:
    """One running task: a breathing word (or the tool's verb), then what
    it is and for how long. Formatted-text fragments, because the word
    carries its own breathing style class."""
    elapsed = now - record.started_at if record.started_at is not None else 0.0
    if record.phase == "gather" or not record.verb:
        word = breath_word(record.task_id, elapsed)
    else:
        word = record.verb
    steps = f" · {record.steps} step{'s' if record.steps != 1 else ''}" if record.steps else ""
    return [
        (breath_class(now), f"{spark(now, unicode=unicode)} "),
        *breathing_word(word, now, unicode=unicode),
        ("class:sim.footer", _line(f"  {record.kind} · {record.short_topic(_topic(_ROW_OVERHEAD))} · {elapsed:.0f}s{steps}")),
    ]


def inflight_rows(record: TaskRecord, *, now: float, unicode: bool = True) -> list[list[tuple[str, str]]]:
    """The call in flight, drawn in place above the prompt the way Claude
    Code shows a running tool: `⏺ run_shell(python -m pytest …)` and,
    hanging from it, how long it has been running. Empty when the task
    is between calls (thinking)."""
    if not record.tool and not record.detail:
        return []
    from .render import display_width, terminal_width

    head = "⏺ " if unicode else "* "
    corner = "  ⎿  " if unicode else "  `- "
    what = f"{record.tool}({record.detail})" if record.tool and record.detail else (record.tool or record.detail)
    what = _fit(what, terminal_width() - display_width(head) - 1)
    since = now - record.inflight_since if record.inflight_since is not None else 0.0
    return [[("class:sim.live", f"{head}{what}")],
            [("class:sim.footer", _line(f"{corner}running… {since:.0f}s"))]]


def done_row(last_done, *, unicode: bool = True) -> list[tuple[str, str]] | None:
    """After the last task of a turn: `✻ Baked for 61s · done 04:33`, kept
    until the next line is typed (Claude Code's own habit)."""
    if not last_done:
        return None
    word, elapsed, when = last_done
    spark = "✻ " if unicode else "* "
    return [("class:sim.footer", _line(f"{spark}{word} for {_took(elapsed)} · done {when}"))]


def live_rows(book: TaskBook, *, now: float, footer_text: str = "", last_done=None,
              unicode: bool = True) -> list[list[tuple[str, str]]]:
    """Everything that sits between the transcript and the prompt: for
    each running task the call in flight (in place) and its breathing
    line; else the redirected one-liner ("Thinking… [4s]"); else what
    just finished. Nothing at all when Sim is idle -- the prompt then
    sits right under the transcript.

    The creator, 2026-09-12, describing the screen bottom-up: the
    status ribbon, a rule, the prompt, a rule, "a dynamic live
    indication section ... with breathing bullet point", and above it
    "a dynamic section showing current activity, process, shell in
    nested format which as system makes progress gets updated in
    place"."""
    rows: list[list[tuple[str, str]]] = []
    running = book.running()
    for record in running[:MAX_RUNNING_ROWS]:
        rows.extend(inflight_rows(record, now=now, unicode=unicode))
        rows.append(running_row(record, now=now, unicode=unicode))
    if len(running) > MAX_RUNNING_ROWS:
        rows.append([("class:sim.footer", f"  … and {len(running) - MAX_RUNNING_ROWS} more running")])
    if not running:
        if footer_text:
            rows.append([("class:sim.footer", _line(footer_text))])
        else:
            done = done_row(last_done, unicode=unicode)
            if done:
                rows.append(done)
    return rows


# ------------------------------------------------- the ribbon (below the prompt)
def agent_row(record: TaskRecord, *, now: float, unicode: bool = True) -> list[tuple[str, str]]:
    """One running task in the ribbon, plainly: what it is and its age.
    The breathing and the call in flight live above the prompt."""
    elapsed = now - record.started_at if record.started_at is not None else 0.0
    mark = "⏺ " if unicode else "* "
    return [("class:sim.footer", _line(f"{mark}{record.kind} · {record.short_topic(_topic(_ROW_OVERHEAD))} · {elapsed:.0f}s"))]


def queued_row(queued: list[TaskRecord], *, unicode: bool = True) -> list[tuple[str, str]] | None:
    if not queued:
        return None
    arrow = "  ↳ " if unicode else "  -> "
    named = "; ".join(t.short_topic(max(16, _topic(_QUEUE_OVERHEAD) // MAX_QUEUED_NAMED))
                      for t in queued[:MAX_QUEUED_NAMED])
    more = f" (+{len(queued) - MAX_QUEUED_NAMED})" if len(queued) > MAX_QUEUED_NAMED else ""
    return [("class:sim.footer", _line(f"{arrow}{len(queued)} queued: {named}{more}"))]


def status_row(*, auto: str, posture: str, model: str, budget: str, hint: str = "") -> list[tuple[str, str]]:
    """The always-there last line: is auto mode on, how guarded is
    Guardian, what model is answering, and how much budget is left.

    Drops the least important parts rather than overrunning a narrow
    terminal -- `auto` is what someone actually scans for, the hint is
    what they already know. Caught by the width assertion, 2026-09-08;
    eleven observers had missed it."""
    from .render import display_width, terminal_width

    parts = [f"⏵⏵ auto {auto}" if auto == "on" else f"auto {auto}"]
    if posture and posture != "unknown":
        parts.append(posture)
    if model:
        parts.append(model)
    if budget:
        parts.append(budget)
    if hint:
        parts.append(hint)
    width = terminal_width()
    while len(parts) > 1 and display_width(" · ".join(parts)) > width:
        parts.pop()  # least important first: hint, budget, model, posture
    return [("class:sim.status", _line(" · ".join(parts)))]


def footer_rows(book: TaskBook, *, now: float, auto: str, posture: str = "", model: str = "",
                budget: str = "", hint: str = "", unicode: bool = True) -> list[list[tuple[str, str]]]:
    """The ribbon at the very bottom, top row first: the running tasks
    (the agents), the queue, and the status row. `idle` when nothing runs."""
    rows: list[list[tuple[str, str]]] = []
    running = book.running()
    for record in running[:MAX_RUNNING_ROWS]:
        rows.append(agent_row(record, now=now, unicode=unicode))
    if len(running) > MAX_RUNNING_ROWS:
        rows.append([("class:sim.footer", f"  … and {len(running) - MAX_RUNNING_ROWS} more running")])
    if not running:
        rows.append([("class:sim.footer", "idle")])
    queued = queued_row(book.queued(), unicode=unicode)
    if queued:
        rows.append(queued)
    rows.append(status_row(auto=auto, posture=posture, model=model, budget=budget, hint=hint))
    return rows


def flatten(rows: list[list[tuple[str, str]]]) -> list[tuple[str, str]]:
    """Rows -> one formatted-text list with newlines between rows, the
    shape `prompt_toolkit`'s toolbar wants."""
    out: list[tuple[str, str]] = []
    for i, row in enumerate(rows):
        if i:
            out.append(("", "\n"))
        out.extend(row)
    return out


def plain(rows: list[list[tuple[str, str]]]) -> str:
    """The same rows as plain lines, for a terminal with no prompt
    toolbar (or a test)."""
    return "\n".join("".join(text for _style, text in row) for row in rows)


def budget_summary(budget: dict) -> str:
    """`{provider: {calls, max_calls, exhausted}}` -> `together 12/200`."""
    for name, entry in (budget or {}).items():
        calls = entry.get("calls")
        cap = entry.get("max_calls")
        if entry.get("exhausted"):
            return f"{name} budget exhausted"
        if calls is not None and cap:
            return f"{name} {calls}/{cap}"
        if calls is not None:
            return f"{name} {calls} calls"
    return ""


__all__ = [
    "BREATH_PERIOD_S", "BREATH_ROTATE_S", "BREATH_SHADES", "BREATH_WORDS",
    "SPARK_FRAMES", "agent_row", "breath_class", "breath_shade", "breath_word", "breathing_word", "budget_summary",
    "done_row", "flatten", "spark",
    "footer_rows", "inflight_rows", "live_rows", "plain", "queued_row", "running_row", "status_row", "tree_end",
    "tree_note", "tree_start", "tree_step",
]
