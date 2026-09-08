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
    │   ├─ read_file simorgh/interface/vitals.py     ✓  0.3s   │
    │   ├─ apply_source_patch simorgh/interface/vit… ✓  1.2s   │
    │   │  --- a/simorgh/interface/vitals.py                   │
    │   │  +++ b/simorgh/interface/vitals.py                   │
    │   │  +\"\"\"A real local projection …\"\"\"                     │
    │   ├─ run_tests                                 ✓ 42.0s   │
    │   ╰─ ✅ completed in 60s                                  │
    ├ input ──────────────────────────────────────────────────┤
    │ > _                                                      │
    ├ activity ───────────────────────────────────────────────┤
    │ ✻ Osmosing…  research · what does memory export · 12s    │
    │   ↳ 2 queued: tighten the retry loop; plan web access    │
    │ auto on · guarded · GLM-5.3-Flash · together 12/200      │
    └──────────────────────────────────────────────────────────┘
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


# ------------------------------------------------------------ transcript tree
_OK = {True: "✓", False: "✗"}
_END_ICON = {"completed": "✅", "failed": "❌", "blocked": "⏸", "paused": "⏸"}
_KIND_ICON = {"research": "🔍", "patch": "🔧", "skill": "🎓", "project": "🗂", "chat": "💬"}


def _topic(overhead: int) -> int:
    from .render import terminal_width

    return max(24, terminal_width() - overhead)


def _fit(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


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
    return f"{head} {icon} {record.kind} · {record.origin} · {record.short_topic()}  [{record.task_id[:8]}]"


def tree_step(*, tool: str | None, head: str, ok: bool | None, took: float | None,
              width: int | None = None, unicode: bool = True) -> str:
    """One tool call as a branch: `├─ tool what  ✓ 0.3s`.

    Every step is a `├─` because when it prints nobody knows yet whether
    it is the last; the end line (`tree_end`) closes the tree with `╰─`.
    """
    from .render import terminal_width

    width = (terminal_width() - _TREE_OVERHEAD) if width is None else width
    branch = "  ├─ " if unicode else "  |- "
    what = f"{tool} {head}" if tool else head
    what = _fit(what, width - len(branch) - 10)
    mark = _OK.get(ok, "…") if unicode else {True: "ok", False: "FAILED"}.get(ok, "..")
    tail = f"{mark} {_took(took)}".rstrip()
    pad = max(1, width - len(branch) - len(what) - len(tail))
    return f"{branch}{what}{' ' * pad}{tail}"


def tree_note(lines: list[str], *, unicode: bool = True) -> list[str]:
    """Lines that belong *under* a branch -- a diff, a test summary --
    kept inside the tree's rail so the eye can follow it."""
    rail = "  │  " if unicode else "  |  "
    return [f"{rail}{line}" for line in lines]


def tree_end(record: TaskRecord, *, elapsed: float | None, detail: str = "", unicode: bool = True) -> str:
    icon = _END_ICON.get(record.status, "•") if unicode else ""
    corner = "  ╰─ " if unicode else "  `- "
    took = f" in {_took(elapsed)}" if elapsed is not None else ""
    tail = f" -- {_fit(detail, 80)}" if detail else ""
    return f"{corner}{icon} {record.status}{took}{tail}".replace("  ", " ", 0)


# ---------------------------------------------------------------- bottom rows
def running_row(record: TaskRecord, *, now: float, unicode: bool = True) -> list[tuple[str, str]]:
    """One running task: a breathing word (or the tool's verb), then what
    it is and for how long. Formatted-text fragments, because the word
    carries its own breathing style class."""
    elapsed = now - record.started_at if record.started_at is not None else 0.0
    if record.phase == "gather" or not record.verb:
        word = breath_word(record.task_id, elapsed)
    else:
        word = record.verb
    spark = "✻ " if unicode else "* "
    steps = f" · {record.steps} step{'s' if record.steps != 1 else ''}" if record.steps else ""
    return [
        (breath_class(now), f"{spark}{word}…"),
        ("class:sim.footer", f"  {record.kind} · {record.short_topic(_topic(_ROW_OVERHEAD))} · {elapsed:.0f}s{steps}"),
    ]


def queued_row(queued: list[TaskRecord], *, unicode: bool = True) -> list[tuple[str, str]] | None:
    if not queued:
        return None
    arrow = "  ↳ " if unicode else "  -> "
    named = "; ".join(t.short_topic(max(16, _topic(_QUEUE_OVERHEAD) // MAX_QUEUED_NAMED))
                      for t in queued[:MAX_QUEUED_NAMED])
    more = f" (+{len(queued) - MAX_QUEUED_NAMED})" if len(queued) > MAX_QUEUED_NAMED else ""
    return [("class:sim.footer", f"{arrow}{len(queued)} queued: {named}{more}")]


def status_row(*, auto: str, posture: str, model: str, budget: str, hint: str = "") -> list[tuple[str, str]]:
    """The always-there last line: is auto mode on, how guarded is
    Guardian, what model is answering, and how much budget is left."""
    parts = [f"auto {auto}"]
    if posture and posture != "unknown":
        parts.append(posture)
    if model:
        parts.append(model)
    if budget:
        parts.append(budget)
    if hint:
        parts.append(hint)
    return [("class:sim.status", " · ".join(parts))]


def footer_rows(book: TaskBook, *, now: float, auto: str, posture: str = "", model: str = "",
                budget: str = "", hint: str = "", unicode: bool = True) -> list[list[tuple[str, str]]]:
    """The whole bottom section, top row first."""
    rows: list[list[tuple[str, str]]] = []
    running = book.running()
    for record in running[:MAX_RUNNING_ROWS]:
        rows.append(running_row(record, now=now, unicode=unicode))
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
    "breath_class", "breath_shade", "breath_word", "budget_summary", "flatten", "footer_rows",
    "plain", "queued_row", "running_row", "status_row", "tree_end", "tree_note", "tree_start", "tree_step",
]
