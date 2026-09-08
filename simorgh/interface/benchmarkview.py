"""The `benchmark` command's own rendering and argument parsing.

Kept out of `dispatch.py` because every other command there fits in a
handful of lines and this one does not: it has sub-verbs, an option
grammar, and four views. The charts themselves come from
`benchmarkchart.py`; both work on the plain payload dicts the bus
carries, never on the benchmark package's own types -- subsystems may
not import each other.
"""

from __future__ import annotations

import re

from .benchmarkchart import compare, history as history_chart, summary

_LEVEL = re.compile(r"(?:^|\s)level=([^\s]+)", re.I)
_COUNT = re.compile(r"(?:^|\s)(\d{1,4})(?=\s|$)")


def parse_run(rest: str) -> tuple[dict, str]:
    """`<suite> [n] [level=L] [refresh]` -> (payload, problem)."""
    text = " " + (rest or "").strip()
    payload: dict = {}
    level = _LEVEL.search(text)
    if level:
        payload["level"] = level.group(1)
        text = text[: level.start()] + text[level.end():]
    if re.search(r"(?:^|\s)refresh(?=\s|$)", text, re.I):
        payload["refresh"] = True
        text = re.sub(r"(?:^|\s)refresh(?=\s|$)", " ", text, flags=re.I)
    count = _COUNT.search(text)
    if count:
        payload["limit"] = int(count.group(1))
        text = text[: count.start()] + text[count.end():]
    suite = text.strip()
    if not suite:
        return {}, "usage: benchmark run <suite> [n] [level=L] [refresh]  --  `benchmark suites` lists them"
    payload["suite"] = suite.split()[0]
    return payload, ""


def _records(payload: dict) -> list[dict]:
    return list(payload.get("runs") or [])


def started(payload: dict) -> str:
    return (
        f"benchmark started: {payload.get('suite')} · {payload.get('cases')} cases · "
        f"as {payload.get('model')} · run {payload.get('run_id')}\n"
        "  progress is narrated as it goes; `benchmark` shows the result when it lands"
    )


def suites(payload: dict) -> str:
    lines = [f"benchmarks available  (answering as {payload.get('model', 'unknown')})"]
    for suite in payload.get("suites") or []:
        marks = []
        if suite.get("gated"):
            marks.append("gated")
        if not suite.get("scorable"):
            marks.append("load-only")
        cached = suite.get("cached_cases") or 0
        marks.append(f"{cached} cached" if cached else "not downloaded")
        lines.append(f"  {suite['name']:<20} {suite.get('description', '')}")
        lines.append(f"  {'':<20} {suite.get('dataset', '')}  [{', '.join(marks)}]")
        if not suite.get("scorable") and suite.get("why_not_scorable"):
            lines.append(f"  {'':<20} note: {suite['why_not_scorable']}")
    if payload.get("running"):
        lines.append("  a run is in flight; `benchmark history` shows where it is")
    return "\n".join(lines)


def latest(payload: dict) -> str:
    records = _records(payload)
    if not records:
        return "no benchmark runs yet -- `benchmark run bfcl-parallel 5` makes the first one"
    newest: dict[tuple[str, str], dict] = {}
    for record in sorted(records, key=lambda r: float(r.get("started_at") or 0.0)):
        newest[(record.get("suite", ""), record.get("model", ""))] = record
    lines = [summary(record) for record in newest.values()]
    progress = payload.get("progress") or {}
    if payload.get("running") and progress:
        lines.append(
            f"  in flight: {progress.get('suite')} {progress.get('index', 0)}/{progress.get('total', 0)}"
            f"  {progress.get('correct', 0)}/{progress.get('attempted', 0)} correct so far"
        )
    return "\n".join(lines)


def history(payload: dict) -> str:
    records = _records(payload)
    if not records:
        return "no benchmark runs recorded yet"
    text = history_chart(records)
    by_suite: dict[str, list[dict]] = {}
    for record in sorted(records, key=lambda r: float(r.get("started_at") or 0.0)):
        by_suite.setdefault(str(record.get("suite", "")), []).append(record)
    for suite, runs in by_suite.items():
        if len(runs) > 1:
            text += "\n\n" + compare(runs[-2], runs[-1])
    return text


def detail(payload: dict) -> str:
    records = _records(payload)
    if not records:
        return "no such run"
    record = records[0]
    lines = [summary(record), ""]
    for result in record.get("cases") or []:
        skipped, correct = bool(result.get("skipped")), bool(result.get("correct"))
        mark = "·" if skipped else ("✓" if correct else "✗")
        note = result.get("error") or (
            f"answered {str(result.get('answer', ''))[:60]!r}, expected {str(result.get('expected', ''))[:60]!r}"
            if not correct and not skipped else ""
        )
        level = str(result.get("level") or "")
        lines.append(
            f"  {mark} {str(result.get('case_id', '')):<34} {level:<14.14} "
            f"{float(result.get('seconds') or 0.0):5.0f}s  {note}"
        )
    return "\n".join(lines)


__all__ = ["detail", "history", "latest", "parse_run", "started", "suites"]
