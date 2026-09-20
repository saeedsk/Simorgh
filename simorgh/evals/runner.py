"""Run a suite N times and say what it scored (stage 4 item 9).

The repeats are the point. One run of a small suite is a coin flip
dressed as a measurement -- the trial suite has scored 5, 6 and 7 out of
7 on the same commit -- so `run` takes the suite N times, pools the
outcomes, and reports a pass rate with a 95% bootstrap interval. A bless
comparing two commits compares intervals, not numbers.

Nothing here knows what any suite does. It counts, times, formats and
writes the record; the suites do the work.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from .api import Report, outcomes_from
from .suites import find, timed

#: Where a run's record lands, under the data directory. Kept as JSON
#: lines: a bless reads the last line for its decision log, and a human
#: reads the file.
RECORD_NAME = "evals.jsonl"


#: Set in a child process so it runs exactly one repeat, in process.
ONE_ENV = "SIMORGH_EVALS_ONE"


async def run(suite: str, *, repeats: int = 1, isolate: bool | None = None) -> Report:
    """Run `suite` `repeats` times and pool the outcomes.

    Each repeat is its own process by default. That is not tidiness: a
    suite that boots the whole system leaves torch models, threads and a
    warmed embedder behind it, and the second boot in one interpreter
    segfaults. A separate process is also what a repeat is supposed to
    be -- a fresh start, not a continuation of the last one.
    """
    runner = find(suite)
    report = Report(suite=suite, repeats=max(1, repeats))
    if isolate is None:
        isolate = not os.environ.get(ONE_ENV)
    started = time.monotonic()
    for index in range(report.repeats):
        if isolate:
            report.outcomes.extend(await _one_in_a_child(suite, index))
        else:
            outcomes, _seconds = await timed(runner)
            report.outcomes.extend(outcomes)
    report.seconds = time.monotonic() - started
    return report


async def _one_in_a_child(suite: str, index: int) -> list:
    """One repeat, in a child interpreter, as JSON."""
    env = {**os.environ, ONE_ENV: "1"}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "simorgh.evals", "run", suite, "--repeats", "1", "--json",
        "--paid", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
        cwd=str(Path(__file__).resolve().parents[2]))
    out, err = await proc.communicate()
    text = out.decode("utf-8", "replace").strip()
    try:
        return outcomes_from(json.loads(text).get("cases") or [])
    except ValueError:
        # A repeat that died is one skipped case saying so, not a
        # silently smaller denominator.
        from .api import Case, Outcome, SKIPPED

        tail = (err.decode("utf-8", "replace").strip() or text)[-200:]
        return [Outcome(case=Case(name=f"repeat {index + 1}", kind=suite), status=SKIPPED,
                        why=f"the repeat did not finish: {tail}")]


def table(report: Report) -> str:
    """The report as a table a person reads in a terminal."""
    low, high = report.interval()
    lines = [
        f"{report.suite}: {report.passed}/{report.total} "
        f"({report.rate:.0%}, 95% CI {low:.0%}-{high:.0%}) "
        f"over {report.repeats} repeat(s) in {report.seconds:.1f} s"
        + (f", ${report.cost_usd:.3f}" if report.cost_usd else "")
        + (f", {report.skipped} skipped" if report.skipped else ""),
    ]
    levels = report.by_level()
    if len(levels) > 1 or (levels and "-" not in levels):
        lines.append("  " + "  ".join(f"{level} {passed}/{total}"
                                      for level, (passed, total) in levels.items()))
    lines.append(f"  {'case':<24} {'result':<8} {'s':>6}  why")
    seen: set[str] = set()
    for outcome in report.outcomes:
        # Over repeats the same case appears N times; show each case
        # once, with the first run that was not a pass, because that is
        # the line somebody is going to act on.
        name = outcome.case.name
        if name in seen and outcome.passed:
            continue
        seen.add(name)
        lines.append(f"  {name:<24} {outcome.status:<8} {outcome.seconds:>6.1f}  {outcome.why[:60]}")
    return "\n".join(lines)


def record(report: Report, *, data_dir: str | Path) -> Path:
    """Append the report to `<data_dir>/evals.jsonl` and return the path.

    Appended, never rewritten, for the same reason the Ledger is: the
    interesting question about an eval is almost always what it did last
    week, not what it did just now.
    """
    path = Path(data_dir) / RECORD_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": time.time(), **report.as_dict()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")
    return path


def last(data_dir: str | Path, *, suite: str = "") -> dict | None:
    """The most recent recorded report, optionally for one suite."""
    path = Path(data_dir) / RECORD_NAME
    if not path.exists():
        return None
    found = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if suite and row.get("suite") != suite:
            continue
        found = row
    return found


__all__ = ["ONE_ENV", "RECORD_NAME", "last", "record", "run", "table"]
