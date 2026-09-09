"""Benchmark results as text and as unicode graphics.

Lives in `interface` rather than `benchmark` because subsystems may not
import each other (`tests/simorgh/test_module_boundaries.py`) -- and
because this is presentation, which is the interface's job. It works on
the plain payload dicts `benchmark.history.reply` carries, never on the
benchmark package's own types.

The creator, 2026-09-07: results "in user friendly textual and graphical
(using unicode characters) on cli". Three views, all pure functions over
`RunRecord`s so they are testable without a terminal:

- `summary`   one run: accuracy overall and per level, with bars
- `history`   accuracy over time per model, as a braille line chart
- `compare`   two runs of the same suite, case by case, what moved

Braille (U+2800..) rather than block characters for the line chart:
each cell carries a 2x4 grid of dots, so a 60-column chart plots 120
points at 4x the vertical resolution a block chart manages. Blocks are
still right for a bar -- there the eye is comparing lengths, not
following a line.
"""

from __future__ import annotations

import time

_BLOCKS = " ▏▎▍▌▋▊▉█"
# Braille dot bit values, by (column, row) within one cell.
_DOTS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
_LEVEL_NAMES = {"1": "Level 1", "2": "Level 2", "3": "Level 3", "": "all"}


def _level_name(level: str) -> str:
    """"Level 1" for a GAIA tier; the bare word for a BFCL category --
    "Level live_parallel" was simply wrong (observer, 2026-09-08)."""
    if level in _LEVEL_NAMES:
        return _LEVEL_NAMES[level]
    return f"Level {level}" if level.isdigit() else level


def bar(fraction: float, width: int = 24) -> str:
    """A bar with eighth-of-a-cell resolution, so 1/48th still shows."""
    fraction = min(1.0, max(0.0, fraction))
    whole, remainder = divmod(fraction * width * 8, 8)
    whole = int(whole)
    out = "█" * whole
    if whole < width:
        out += _BLOCKS[int(remainder)]
    return (out + " " * width)[:width]


_TRACK = "░"


def track_bar(fraction: float, width: int = 24) -> str:
    """`bar`, but the unfilled remainder is drawn rather than left blank.

    A blank remainder means 0% renders as nothing at all: a suite that
    scored zero showed an empty gap where every other row had a bar, so
    the one result you most want to see was the one that looked like a
    rendering glitch. A track makes the scale visible and every row the
    same shape (creator, 2026-09-09: "not clean ... prefer proper
    tabling")."""
    filled = bar(fraction, width).rstrip()
    return filled + _TRACK * (width - len(filled))


def accuracy_color(fraction: float) -> str:
    """Green/amber/red by accuracy. Deliberately coarse -- the number is
    right there; the colour is for finding the bad row at a glance."""
    if fraction >= 0.7:
        return "green"
    if fraction >= 0.4:
        return "yellow"
    return "red"


def sparkline(values: list[float], *, lo: float = 0.0, hi: float = 1.0) -> str:
    """One row of block characters -- a trend at a glance, in a footer."""
    if not values:
        return ""
    span = (hi - lo) or 1.0
    steps = "▁▂▃▄▅▆▇█"
    return "".join(steps[min(len(steps) - 1, max(0, int((v - lo) / span * (len(steps) - 1) + 0.5)))] for v in values)


def braille_chart(series: list[tuple[str, list[float]]], *, width: int = 56, height: int = 4,
                  lo: float = 0.0, hi: float = 1.0) -> list[str]:
    """A line chart, `height` text rows tall, one line per series.

    Each cell is a 2x4 braille grid, so the real resolution is
    `width * 2` across and `height * 4` down. Series are drawn into the
    same grid; the legend below names them, since braille cannot carry
    colour on its own (`interface/render.py` colours whole rows where a
    terminal supports it)."""
    grid = [[0] * width for _ in range(height)]
    span = (hi - lo) or 1.0
    for _name, values in series:
        if not values:
            continue
        points = width * 2
        for x in range(points):
            # Sample the series across the full width even when it has
            # fewer points than columns, so two runs still draw a line
            # rather than a dot in the corner.
            index = 0 if len(values) == 1 else round(x * (len(values) - 1) / (points - 1))
            value = min(hi, max(lo, values[index]))
            rows = height * 4
            y = rows - 1 - min(rows - 1, int((value - lo) / span * (rows - 1) + 0.5))
            grid[y // 4][x // 2] |= _DOTS[x % 2][y % 4]
    return ["".join(chr(0x2800 + cell) for cell in row) for row in grid]


def _acc(run: dict) -> float:
    attempted = int(run.get("attempted") or 0)
    return (int(run.get("correct") or 0) / attempted) if attempted else 0.0


def _levels(run: dict) -> dict:
    return {str(k): (int(v[0]), int(v[1])) for k, v in sorted((run.get("by_level") or {}).items())}


def _pct(correct: int, attempted: int) -> str:
    return f"{(correct / attempted * 100 if attempted else 0):5.1f}%"


def _ago(when: float, *, now: float | None = None) -> str:
    seconds = max(0.0, (now if now is not None else time.time()) - when)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{int(seconds // size)}{unit} ago"
    return "just now"


def summary(record: dict, *, width: int = 24, enabled: bool | None = None) -> str:
    """One run, in full, as a table.

    Every number the old layout showed is still here; what changed is
    that they line up. Before (creator, 2026-09-09), the overall row and
    the per-level rows were built by different format strings with
    different padding, so nothing shared a column: the headline accuracy
    floated far right of the level accuracies beneath it, the counts sat
    at a third position, and a 0% run drew no bar at all. Now the
    overall row is simply the first row of the same grid, and the
    metadata that used to crowd the title has its own dim line.
    """
    import sys

    from .render import color_enabled, style

    # `color_enabled()` answers the NO_COLOR question only -- it is
    # deliberately not tty-aware, because most callers already know
    # whether they are writing to a terminal. This one does not: the
    # benchmark views are pure `payload -> str` functions several layers
    # below the REPL that holds that flag. Ask the terminal directly, so
    # `benchmark > file` and a piped CI log get clean text rather than
    # escape codes, the same rule `live_status_enabled` follows.
    on = (color_enabled() and sys.stdout.isatty()) if enabled is None else enabled
    correct, attempted = int(record.get("correct") or 0), int(record.get("attempted") or 0)
    skipped = int(record.get("skipped") or 0)

    rows: list[tuple[str, int, int]] = [("overall", correct, attempted)]
    by_level = _levels(record)
    if len(by_level) > 1 or (by_level and "" not in by_level):
        # A GAIA level is "1"; a BFCL one is "live_parallel".
        rows.extend((_level_name(level), c, a) for level, (c, a) in by_level.items())

    label_w = max(len(name) for name, _, _ in rows)
    correct_w = max(len(str(c)) for _, c, _ in rows)
    attempted_w = max(len(str(a)) for _, _, a in rows)

    title = f"{record.get('suite', '?')} · {record.get('model', '?')}"
    head = style(title, "bold", enabled=on)
    if record.get("partial"):
        head += "  " + style("[partial]", "yellow", enabled=on)
    if record.get("note"):
        head += "  " + style(f"({record['note']})", "dim", enabled=on)
    lines = [head]

    # Everything that identifies the run, on one dim line instead of
    # scattered across the title and a trailing row.
    meta = [str(record.get("run_id") or "")]
    meta.append(f"suite {record.get('suite_version', 'unknown')}")
    meta.append(f"{float(record.get('seconds') or 0.0):.0f}s")
    cost_usd = float(record.get("cost_usd") or 0.0)
    if cost_usd:
        meta.append(f"${cost_usd:.4f}")
    if skipped:
        meta.append(f"{skipped} skipped")
    lines.append("  " + style(" · ".join(m for m in meta if m), "dim", enabled=on))
    lines.append("")

    for name, row_correct, row_attempted in rows:
        fraction = (row_correct / row_attempted) if row_attempted else 0.0
        colour = accuracy_color(fraction)
        lines.append(
            f"  {name:<{label_w}}  "
            + style(track_bar(fraction, width), colour, enabled=on)
            + "  " + style(_pct(row_correct, row_attempted), colour, enabled=on)
            + f"  {row_correct:>{correct_w}}/{row_attempted:<{attempted_w}}"
        )

    blocked = int(record.get("blocked") or 0)
    if blocked:
        # The line that says whether our own pipeline is the problem,
        # rather than the model.
        kept = int(record.get("blocked_but_correct") or 0)
        text = f"{blocked} answer{'s' if blocked != 1 else ''} our own pipeline stopped"
        if kept:
            text += f", {kept} of them right"
        lines.append("  " + style(f"⚠ {text}", "yellow", enabled=on))
    return "\n".join(lines)


def history(records: list[dict], *, width: int = 56, height: int = 4) -> str:
    """Accuracy over time, one line per model, oldest run on the left."""
    if not records:
        return "no benchmark runs recorded yet -- `benchmark run gaia` makes the first one"
    ordered = sorted(records, key=lambda r: float(r.get("started_at") or 0.0))
    by_model: dict[str, list[dict]] = {}
    for record in ordered:
        by_model.setdefault(str(record.get("model") or "unknown"), []).append(record)

    series = [(model, [_acc(r) for r in runs]) for model, runs in by_model.items()]
    lines = ["  100% ┤" + row if i == 0 else "       │" + row
             for i, row in enumerate(braille_chart(series, width=width, height=height))]
    # The prefix "       │" is 8 characters, not 7; slicing at 7 left the
    # bar in place and shifted the whole row (observer, 2026-09-08).
    lines[-1] = "    0% ┤" + lines[-1][8:]
    lines.append("       └" + "─" * width)
    span = f"{_ago(float(ordered[0].get('started_at') or 0.0))} → {_ago(float(ordered[-1].get('started_at') or 0.0))}"
    lines.append(f"        {span:<{width}}")
    for model, runs in by_model.items():
        latest = runs[-1]
        trend = sparkline([_acc(r) for r in runs])
        change = ""
        if len(runs) > 1:
            delta = (_acc(latest) - _acc(runs[-2])) * 100
            change = f"  {'▲' if delta > 0 else '▼' if delta < 0 else '='}{abs(delta):.1f}pt"
        lines.append(
            f"  {model:<22} {trend:<12} {_pct(int(latest.get('correct') or 0), int(latest.get('attempted') or 0))}"
            f"  ({len(runs)} run{'s' if len(runs) != 1 else ''}){change}"
        )
    return "\n".join(lines)


def _cases(run: dict) -> dict:
    return {c.get("case_id", ""): c for c in (run.get("cases") or []) if not c.get("skipped")}


def compare(before: dict, after: dict, *, limit: int = 12) -> str:
    """What moved between two runs -- the view that says whether a
    change helped, which is the only reason to keep history at all."""
    old, new = _cases(before), _cases(after)
    shared = [cid for cid in new if cid in old]
    fixed = [cid for cid in shared if new[cid].get("correct") and not old[cid].get("correct")]
    broken = [cid for cid in shared if old[cid].get("correct") and not new[cid].get("correct")]
    delta = (_acc(after) - _acc(before)) * 100
    lines = [
        f"{before.get('model', '?')} ({_pct(int(before.get('correct') or 0), int(before.get('attempted') or 0))}) → "
        f"{after.get('model', '?')} ({_pct(int(after.get('correct') or 0), int(after.get('attempted') or 0))})   "
        f"{'▲' if delta > 0 else '▼' if delta < 0 else '='}{abs(delta):.1f}pt over {len(shared)} shared cases",
        f"  fixed   {len(fixed)}",
        f"  broke   {len(broken)}",
    ]
    for cid in broken[:limit]:
        lines.append(
            f"    ✗ {cid}  expected {str(new[cid].get('expected', ''))[:40]!r}, "
            f"answered {str(new[cid].get('answer', ''))[:40]!r}"
        )
    if len(broken) > limit:
        lines.append(f"    ... and {len(broken) - limit} more")
    return "\n".join(lines)


__all__ = ["bar", "braille_chart", "compare", "history", "sparkline", "summary"]
