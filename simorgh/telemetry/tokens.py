"""Where a turn's tokens go (stage 17 item 1): the `cognition.provider_call`
spans of a period, summed per provider and per lane (chat, voice, task).

Each span carries the provider's own `tokens_in` and `tokens_cached` and,
since stage 17, `split`: Cognition's chars/4 estimate of the input per
block (`cognition/tokens.py::BLOCKS`). The estimate gives shares; the
shares are scaled to `tokens_in`, so the totals are the provider's
counts. A provider caches a prefix, so the cached tokens are taken off
the blocks in the order they were sent (system prefix, tool block,
then the user turn); what is left of each block is its uncached part.
That is an approximation where a provider puts native tool schemas
somewhere else, and it is labelled one.

Reads token counts and nothing else: no prompt text is in a span."""

from __future__ import annotations

import re
import time
from pathlib import Path

from .store import read_spans

SPAN = "cognition.provider_call"
#: Must match `cognition/tokens.py::BLOCKS` (telemetry may not import
#: cognition, `tests/simorgh/test_module_boundaries.py`).
BLOCKS = ("prefix", "tools", "memory", "question", "window", "results")

_SINCE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw]?)\s*$")
_UNIT = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86_400.0, "w": 604_800.0}


def parse_since(text: str) -> float:
    """`7d`, `12h`, `30m`, `90s` or a bare number of seconds -> seconds."""
    match = _SINCE.match(str(text))
    if not match:
        raise ValueError(f"--since wants a number with s/m/h/d/w, not {text!r}")
    return float(match.group(1)) * _UNIT[match.group(2)]


def lane_of(attrs: dict) -> str:
    """`voice` when the think said it came from a voice turn, `chat` for any
    other chat-purpose think, `task` for the rest."""
    if str(attrs.get("channel") or "") == "voice":
        return "voice"
    return "chat" if str(attrs.get("purpose") or "") == "chat" else "task"


def _int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def span_blocks(attrs: dict) -> tuple[dict[str, float], dict[str, float]] | None:
    """One span's input per block, scaled to its `tokens_in`, and the
    uncached part of each; None when the span carries no split."""
    split = attrs.get("split")
    if not isinstance(split, dict):
        return None
    est = {b: float(_int(split.get(b))) for b in BLOCKS}
    est_total = sum(est.values())
    if est_total <= 0:
        return None
    real = _int(attrs.get("tokens_in")) or est_total
    scaled = {b: v * real / est_total for b, v in est.items()}
    cached = min(float(_int(attrs.get("tokens_cached"))), float(real))
    uncached = {}
    for block in BLOCKS:
        taken = min(cached, scaled[block])
        cached -= taken
        uncached[block] = scaled[block] - taken
    return scaled, uncached


def _empty() -> dict:
    return {"calls": 0, "split_calls": 0, "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0,
            "blocks": {b: 0.0 for b in BLOCKS}, "uncached": {b: 0.0 for b in BLOCKS}}


def summarize(spans: list[dict]) -> dict:
    """`{"by_provider": {name: row}, "by_lane": {lane: row}, "all": row}`;
    a row is calls, the token sums, `cache_hit` (cached / in) and, over
    the calls that carry a split, `blocks`/`uncached` per block and their
    `share`/`uncached_share`."""
    by_provider: dict[str, dict] = {}
    by_lane: dict[str, dict] = {}
    total = _empty()
    for span in spans:
        attrs = span.get("attrs") or {}
        rows = (by_provider.setdefault(str(attrs.get("provider") or "?"), _empty()),
                by_lane.setdefault(lane_of(attrs), _empty()), total)
        blocks = span_blocks(attrs)
        for row in rows:
            row["calls"] += 1
            row["tokens_in"] += _int(attrs.get("tokens_in"))
            row["tokens_cached"] += min(_int(attrs.get("tokens_cached")), _int(attrs.get("tokens_in")))
            row["tokens_out"] += _int(attrs.get("tokens_out"))
            if blocks is not None:
                row["split_calls"] += 1
                for b in BLOCKS:
                    row["blocks"][b] += blocks[0][b]
                    row["uncached"][b] += blocks[1][b]
    for row in (*by_provider.values(), *by_lane.values(), total):
        _finish(row)
    return {"by_provider": by_provider, "by_lane": by_lane, "all": total}


def _finish(row: dict) -> None:
    row["cache_hit"] = row["tokens_cached"] / row["tokens_in"] if row["tokens_in"] else 0.0
    whole, rest = sum(row["blocks"].values()), sum(row["uncached"].values())
    row["share"] = {b: (v / whole if whole else 0.0) for b, v in row["blocks"].items()}
    row["uncached_share"] = {b: (v / rest if rest else 0.0) for b, v in row["uncached"].items()}
    row["blocks"] = {b: round(v) for b, v in row["blocks"].items()}
    row["uncached"] = {b: round(v) for b, v in row["uncached"].items()}


def report(path: str | Path, *, since_s: float, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    out = summarize(read_spans(path, SPAN, since=now - since_s))
    out["since_s"] = since_s
    out["file"] = str(path)
    return out


def _n(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1000:.0f}k"
    return str(value)


def _row_lines(title: str, row: dict) -> list[str]:
    lines = [f"{title}: {row['calls']} calls, {_n(row['tokens_in'])} in, {_n(row['tokens_cached'])} cached "
             f"({row['cache_hit']:.0%} hit), {_n(row['tokens_out'])} out"]
    if not row["split_calls"]:
        lines.append("  no split recorded (calls before stage 17 item 1)")
        return lines
    if row["split_calls"] < row["calls"]:
        lines.append(f"  split on {row['split_calls']} of {row['calls']} calls")
    lines.append(f"  {'block':9s} {'tokens':>8s} {'share':>6s}  {'uncached':>8s} {'share':>6s}")
    for b in BLOCKS:
        lines.append(f"  {b:9s} {_n(row['blocks'][b]):>8s} {row['share'][b]:6.1%}  "
                     f"{_n(row['uncached'][b]):>8s} {row['uncached_share'][b]:6.1%}")
    return lines


def format_report(result: dict) -> str:
    days = result["since_s"] / 86_400.0
    lines = [f"cognition.provider_call spans over the last {days:g} d ({result['file']}); "
             "blocks estimated chars/4 and scaled to the provider's tokens_in", ""]
    if not result["all"]["calls"]:
        lines.append("no provider calls in this period")
        return "\n".join(lines)
    for name, row in sorted(result["by_provider"].items()):
        lines += _row_lines(f"provider {name}", row) + [""]
    for lane in ("chat", "voice", "task"):
        if lane in result["by_lane"]:
            lines += _row_lines(f"lane {lane}", result["by_lane"][lane]) + [""]
    # The stage 17 gate: tool schemas over 20% of uncached input on chat
    # or voice turns.
    for lane in ("chat", "voice"):
        row = result["by_lane"].get(lane)
        if row and row["split_calls"]:
            share = row["uncached_share"]["tools"]
            lines.append(f"gate ({lane}): tools are {share:.1%} of uncached input "
                         f"({'over' if share > 0.20 else 'not over'} 20%)")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["BLOCKS", "SPAN", "format_report", "lane_of", "parse_since", "report", "span_blocks", "summarize"]
