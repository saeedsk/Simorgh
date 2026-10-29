"""What the tool router would have done (stage 17 item 3): the
`routing.shadow` spans of a period -- one per routed chat turn, written
by `orchestration/session.py::_route_done` -- summed into the numbers
the plan's gate reads.

A span's attributes: `offered` (the groups the router chose), `used`
(the tools the turn called, `tool_more` left out), `used_groups`,
`missed` (used tools the route would not have offered), `more`,
`conversational` (the route was the no-tools conversational one) and
`channel`. The miss rate is the share of turns with any `missed` tool;
routing goes `on` only below 3% (`MISS_GATE`).

Reads group and tool names and nothing else: no prompt text is in a span."""

from __future__ import annotations

import time
from pathlib import Path

from .store import read_spans

#: The span per mode (`routing.<[orchestration] tool_routing>`).
SPANS = {"shadow": "routing.shadow", "on": "routing.on"}
#: The plan's gate: turn routing on only under this miss rate.
MISS_GATE = 0.03


def _names(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if v]


def summarize(spans: list[dict]) -> dict:
    """`turns`, `tool_turns` (turns that used any tool), `missed_turns` and
    `miss_rate` (of all turns), `conversational` turns, `conversational_then_tool`
    and its rate (of the conversational turns), `groups` (`{group: {"offered",
    "used"}}`, turns each), `missed_tools` (`{tool: turns}`) and `by_channel`
    (`{channel: {"turns", "missed_turns"}}`)."""
    out = {"turns": 0, "tool_turns": 0, "missed_turns": 0, "conversational": 0,
           "conversational_then_tool": 0, "groups": {}, "missed_tools": {}, "by_channel": {}}
    for span in spans:
        attrs = span.get("attrs") or {}
        used, missed = _names(attrs.get("used")), _names(attrs.get("missed"))
        channel = str(attrs.get("channel") or "") or "typed"
        row = out["by_channel"].setdefault(channel, {"turns": 0, "missed_turns": 0})
        out["turns"] += 1
        row["turns"] += 1
        if used:
            out["tool_turns"] += 1
        if missed:
            out["missed_turns"] += 1
            row["missed_turns"] += 1
        for tool in dict.fromkeys(missed):
            out["missed_tools"][tool] = out["missed_tools"].get(tool, 0) + 1
        if attrs.get("conversational"):
            out["conversational"] += 1
            if used:
                out["conversational_then_tool"] += 1
        for key, names in (("offered", _names(attrs.get("offered"))), ("used", _names(attrs.get("used_groups")))):
            for group in dict.fromkeys(names):
                out["groups"].setdefault(group, {"offered": 0, "used": 0})[key] += 1
    out["miss_rate"] = out["missed_turns"] / out["turns"] if out["turns"] else 0.0
    out["conversational_then_tool_rate"] = (out["conversational_then_tool"] / out["conversational"]
                                            if out["conversational"] else 0.0)
    return out


def report(path: str | Path, *, since_s: float, mode: str = "shadow", now: float | None = None) -> dict:
    if mode not in SPANS:
        raise ValueError(f"unknown routing mode {mode!r}; expected one of {sorted(SPANS)}")
    now = time.time() if now is None else now
    out = summarize(read_spans(path, SPANS[mode], since=now - since_s))
    out["since_s"] = since_s
    out["mode"] = mode
    out["file"] = str(path)
    return out


def format_report(result: dict) -> str:
    days = result["since_s"] / 86_400.0
    lines = [f"{SPANS[result['mode']]} spans over the last {days:g} d ({result['file']})", ""]
    turns = result["turns"]
    if not turns:
        lines.append("no routed turns in this period")
        return "\n".join(lines) + "\n"
    lines.append(f"turns: {turns} ({result['tool_turns']} used a tool)")
    lines.append(f"miss rate: {result['miss_rate']:.1%} ({result['missed_turns']} of {turns} turns used a tool "
                 "the route would not have offered)")
    lines.append(f"conversational route then a tool: {result['conversational_then_tool_rate']:.1%} "
                 f"({result['conversational_then_tool']} of {result['conversational']} conversational turns)")
    for channel, row in sorted(result["by_channel"].items()):
        rate = row["missed_turns"] / row["turns"] if row["turns"] else 0.0
        lines.append(f"  {channel}: {row['turns']} turns, miss rate {rate:.1%}")
    lines += ["", f"  {'group':16s} {'offered':>7s} {'used':>5s}"]
    for group, row in sorted(result["groups"].items()):
        lines.append(f"  {group:16s} {row['offered']:>7d} {row['used']:>5d}")
    if result["missed_tools"]:
        lines += ["", "missed tools (turns):"]
        for tool, n in sorted(result["missed_tools"].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {tool} {n}")
    lines += ["", f"gate: miss rate {result['miss_rate']:.1%} is "
                  f"{'under' if result['miss_rate'] < MISS_GATE else 'not under'} {MISS_GATE:.0%}"]
    return "\n".join(lines) + "\n"


__all__ = ["MISS_GATE", "SPANS", "format_report", "report", "summarize"]
