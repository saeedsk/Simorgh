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


def _scored(records: list[dict]) -> tuple[list[dict], int]:
    """`(runs that scored at least one case, how many did not)`.

    A run interrupted before any case was scored -- Ctrl-C twenty
    seconds in -- is recorded as partial with 0 attempted, which is
    right: it happened. Plotting it is not: `accuracy` of nothing is
    0.0, and one such run turned `benchmark history` into `0.0%
    (4 runs)  ▼100.0pt` for a model that had resolved every case it
    was ever asked (observer swe-01, 2026-09-10). Empty runs are
    counted and named, never scored."""
    scored = [r for r in records if int(r.get("attempted") or 0) > 0]
    return scored, len(records) - len(scored)


def _empty_note(count: int) -> str:
    if not count:
        return ""
    return (f"  {count} run{'s' if count != 1 else ''} interrupted before any case was scored "
            "-- recorded, not plotted")


def started(payload: dict) -> str:
    # The level is echoed because it may have been RESOLVED: `level=1`
    # at SWE-bench Verified means "<15 min fix", and a run that quietly
    # picked a different level than the one typed is a run whose number
    # means something else.
    level = payload.get("level") or ""
    return (
        f"benchmark started: {payload.get('suite')} · {payload.get('cases')} cases · "
        + (f"level {level} · " if level else "")
        + f"as {payload.get('model')} · run {payload.get('run_id')}\n"
        "  progress is narrated as it goes; `benchmark` shows the result when it lands"
    )


def stopped(payload: dict) -> str:
    return payload.get("detail") or ("stopped" if payload.get("stopped") else "nothing to stop")


def _levels_line(levels: list) -> str:
    """Levels, easiest first, numbered when their names are not already
    numbers -- `level=2` is typed off this line, and SWE-bench
    Verified's levels are durations, so without the ordinal there was
    nothing on screen connecting the two."""
    names = [str(level) for level in levels if str(level)]
    if not names:
        return "none"
    if all(name.isdigit() for name in names):
        return ", ".join(names)
    return " · ".join(f"{i}={name}" for i, name in enumerate(names, 1))


def loaded(payload: dict) -> str:
    lines = [
        f"{payload.get('suite')}: {payload.get('cases')} cases  ·  revision {payload.get('suite_version')}",
        f"  levels: {_levels_line(payload.get('levels') or [])}",
    ]
    needs = int(payload.get("needs_attachment") or 0)
    if needs:
        lines.append(f"  {needs} need a file we do not fetch yet -- those are skipped, never scored wrong")
    if not payload.get("scorable", True):
        lines.append("  load-only: this suite has no honest scorer here yet, so `run` will refuse it")
    lines.append(f"  cached at {payload.get('cache_path')}")
    return "\n".join(lines)


def suites(payload: dict) -> str:
    lines = [f"benchmarks available  (answering as {payload.get('model', 'unknown')})"]
    for suite in payload.get("suites") or []:
        marks = []
        if suite.get("gated"):
            marks.append("gated")
        if not suite.get("scorable"):
            marks.append("load-only")
        if suite.get("needs"):
            marks.append(f"needs {suite['needs']}")
        cached = suite.get("cached_cases") or 0
        marks.append(f"{cached} cached" if cached else "not downloaded")
        lines.append(f"  {suite['name']:<20} {suite.get('description', '')}")
        lines.append(f"  {'':<20} {suite.get('dataset', '')}  [{', '.join(marks)}]")
        if not suite.get("scorable") and suite.get("why_not_scorable"):
            lines.append(f"  {'':<20} note: {suite['why_not_scorable']}")
    if payload.get("running"):
        lines.append("  a run is in flight; `benchmark history` shows where it is")
    return "\n".join(lines)


def _in_flight(payload: dict) -> str:
    progress = payload.get("progress") or {}
    if not payload.get("running") or not progress:
        return ""
    line = (
        f"  in flight: {progress.get('suite')} {progress.get('index', 0)}/{progress.get('total', 0)}"
        f"  {progress.get('correct', 0)}/{progress.get('attempted', 0)} correct so far"
    )
    # The case actually running, and for how long. Typed mid-run, this
    # line used to read "0/2  0/0 correct so far" for as long as the
    # first case took -- true, and useless: nothing named the case or
    # said whether the run was ninety seconds or nine minutes in
    # (observer, 2026-09-10).
    case = str(progress.get("case") or "")
    if case and int(progress.get("index") or 0) < int(progress.get("total") or 0):
        level = str(progress.get("level") or "")
        line += f"\n  now on {case}" + (f" ({level})" if level else "")
        if "case_elapsed_s" in progress:
            line += f" for {_span(float(progress['case_elapsed_s']))}"
    if "elapsed_s" in progress:
        line += f"\n  run started {_span(float(progress['elapsed_s']))} ago"
    return line


def _span(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def progress_line(payload: dict) -> str:
    """One scrolling line per scored case, for `benchmark.progress`.

    `benchmark run` promises "progress is narrated as it goes", and
    until 2026-09-10 nothing narrated it: the service published this
    message after every case and no subscriber existed in the
    interface. A person watching the terminal saw the task's own steps
    (only because autonomous narration happened to be on) and then
    nothing -- not the verdict, not the case's time, not the running
    score (observer, 2026-09-10)."""
    case = str(payload.get("case_id") or "?")
    level = str(payload.get("level") or "")
    if payload.get("case_skipped"):
        verdict = "skipped"
    elif payload.get("case_correct"):
        verdict = "resolved" if payload.get("suite", "").startswith("swebench") else "correct"
    else:
        verdict = "unresolved" if payload.get("suite", "").startswith("swebench") else "wrong"
    seconds = float(payload.get("case_seconds") or 0.0)
    text = (
        f"benchmark {payload.get('index', 0)}/{payload.get('total', 0)} · {case}"
        + (f" ({level})" if level else "")
        + f" · {verdict} in {_span(seconds)}"
        + f" · {payload.get('correct', 0)}/{payload.get('attempted', 0)} so far"
    )
    error = str(payload.get("case_error") or "")
    if error and verdict != "resolved" and verdict != "correct":
        text += f" -- {error[:160]}"
    return text


def latest(payload: dict) -> str:
    records, empty = _scored(_records(payload))
    if not records:
        # A run in flight is not "no runs yet". Both views returned the
        # empty line before ever looking at `running` (observer,
        # 2026-09-08), so `benchmark` during a run said nothing was
        # happening.
        return _in_flight(payload) or (
            _empty_note(empty).strip() or
            "no benchmark runs yet -- `benchmark run bfcl-parallel 5` makes the first one")
    newest: dict[tuple[str, str], dict] = {}
    for record in sorted(records, key=lambda r: float(r.get("started_at") or 0.0)):
        newest[(record.get("suite", ""), record.get("model", ""))] = record
    lines = [summary(record) for record in newest.values()]
    if empty:
        lines.append(_empty_note(empty))
    flight = _in_flight(payload)
    if flight:
        lines.append(flight)
    return "\n".join(lines)


def history(payload: dict) -> str:
    records, empty = _scored(_records(payload))
    if not records:
        return _in_flight(payload) or _empty_note(empty).strip() or "no benchmark runs recorded yet"
    text = history_chart(records)
    if empty:
        text += "\n" + _empty_note(empty)
    by_suite: dict[str, list[dict]] = {}
    for record in sorted(records, key=lambda r: float(r.get("started_at") or 0.0)):
        by_suite.setdefault(str(record.get("suite", "")), []).append(record)
    for suite, runs in by_suite.items():
        if len(runs) > 1:
            text += "\n\n" + compare(runs[-2], runs[-1])
            partial = [r for r in runs[-2:] if r.get("partial")]
            if partial:
                # A stopped 1-case run against a full 2-case run is not
                # two measurements of the same thing; say so next to the
                # comparison rather than leave `[partial]` to `show`.
                text += "\n  " + " · ".join(
                    f"{r.get('run_id')} is partial ({int(r.get('attempted') or 0)} case"
                    f"{'s' if int(r.get('attempted') or 0) != 1 else ''} scored)" for r in partial)
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
        if result.get("blocked_by"):
            # Right answer, stopped by us: neither a pass nor a plain miss.
            mark = "⊘" if correct else mark
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


__all__ = ["detail", "history", "latest", "loaded", "parse_run", "started", "stopped", "suites"]
