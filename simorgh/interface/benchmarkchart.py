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


def bar(fraction: float, width: int = 24) -> str:
    """A bar with eighth-of-a-cell resolution, so 1/48th still shows."""
    fraction = min(1.0, max(0.0, fraction))
    whole, remainder = divmod(fraction * width * 8, 8)
    whole = int(whole)
    out = "█" * whole
    if whole < width:
        out += _BLOCKS[int(remainder)]
    return (out + " " * width)[:width]


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


def summary(record: dict, *, width: int = 24) -> str:
    """One run, in full: the headline, then a bar per level."""
    correct, attempted = int(record.get("correct") or 0), int(record.get("attempted") or 0)
    skipped = int(record.get("skipped") or 0)
    lines = [
        f"{record.get('suite', '?')} · {record.get('model', '?')} · {record.get('run_id', '')}"
        + (f"  ({record['note']})" if record.get("note") else "")
        + ("  [partial]" if record.get("partial") else ""),
        f"  {bar(_acc(record), width)}  {_pct(correct, attempted)}"
        f"  {correct}/{attempted} correct"
        + (f", {skipped} skipped" if skipped else ""),
    ]
    by_level = _levels(record)
    if len(by_level) > 1 or (by_level and "" not in by_level):
        # A GAIA level is "1"; a BFCL one is "live_parallel". Widen the
        # column to the longest name present rather than to a guess, so
        # the bars still line up (watched, 2026-09-08).
        names = {level: _LEVEL_NAMES.get(level, f"Level {level}" if level else "all") for level in by_level}
        column = max((len(n) for n in names.values()), default=9)
        for level, (correct, attempted) in by_level.items():
            lines.append(
                f"    {names[level]:<{column}} {bar(correct / attempted if attempted else 0, width)}"
                f"  {_pct(correct, attempted)}  {correct}/{attempted}"
            )
    column = max((len(_LEVEL_NAMES.get(k, f"Level {k}" if k else "all")) for k in by_level), default=9)
    cost_usd = float(record.get("cost_usd") or 0.0)
    cost = f"  ·  ${cost_usd:.4f}" if cost_usd else ""
    lines.append(
        f"    {'':<{column}} {float(record.get('seconds') or 0.0):.0f}s total{cost}"
        f"  ·  suite {record.get('suite_version', 'unknown')}"
    )
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
    lines[-1] = "    0% ┤" + lines[-1][7:]
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
