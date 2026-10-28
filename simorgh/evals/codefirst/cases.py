"""The five questions, their exact answers, and how a reply is scored
(stage 19 item 8).

Each case is a household question whose answer is a program over more
data than one tool page shows: a rank, an aggregate, a top-N per group,
a windowed count, and a per-item loop. The expected answer is computed
here from the `World` itself, never written down, so a different seed
or a different day is a different and still exact answer.

Scoring is of the ANSWER only (`Score.exact`): every number and every
name the question asks for, read tolerantly (`parse.py`). How the answer
was reached is a separate fact the runner records -- whether a
`run_analysis` action ran (`method.py`) -- because the plan measures
both and they can disagree: a model may compute the right month by a
domain shortcut, or run a program and still answer wrong.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable

from . import parse
from .world import FILES_INDEX, TELEMETRY_LOG, World

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
#: The file types the files question asks about.
FILE_TYPES = ("jpg", "pdf", "mp4")
#: How far an hours figure may be from the exact one and still count:
#: a rounding to the nearest tenth, not a different total.
HOURS_TOLERANCE = 0.05


@dataclass(frozen=True)
class Score:
    exact: bool
    #: "4/5 senders right" -- how near a wrong answer came.
    got: str = ""
    why: str = ""


@dataclass(frozen=True)
class CodeFirstCase:
    id: str
    domain: str
    #: rank | aggregate | top-n | window | per-item
    shape: str
    question: Callable[[World], str]
    expected: Callable[[World], object]
    score: Callable[[str, World], Score]
    #: The tools a model would read this data with, for the record.
    reads: tuple[str, ...] = field(default_factory=tuple)


def _d(day: date) -> str:
    return day.isoformat()


# ------------------------------------------------------------------ mail: top senders
def _sender_aliases(world: World) -> dict[str, tuple[str, ...]]:
    return {s.address: (s.address, s.name) for s in world.senders}


def mail_top_expected(world: World) -> list[tuple[str, int]]:
    """[(address, messages)] for the five who sent the most in the window."""
    lo, hi = world.mail_since, world.mail_until
    counts = Counter(m["from"].split("<")[1].rstrip(">") for m in world.mail
                     if lo <= m["date"].astimezone(timezone.utc).date() <= hi)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]


def _mail_top_question(world: World) -> str:
    return (f"Who are my top 5 email senders by number of messages received from {_d(world.mail_since)} "
            f"through {_d(world.mail_until)} (UTC dates, inclusive)? Count every message in that range, "
            f"and give each sender with their exact count, biggest first.")


def _mail_top_score(answer: str, world: World) -> Score:
    want = mail_top_expected(world)
    aliases = _sender_aliases(world)
    got = parse.segments(answer, aliases)
    right = [addr for addr, n in want if addr in got and parse.first_number(got[addr]) == n]
    ranked = [k for k in parse.order(answer, aliases) if k in dict(want)]
    in_order = ranked == [addr for addr, _ in want]
    why = "" if len(right) == 5 and in_order else (
        f"{len(right)}/5 senders with the right count" + ("" if in_order else "; not in rank order")
        + f"; expected {', '.join(f'{a} {n}' for a, n in want)}")
    return Score(exact=len(right) == 5 and in_order, got=f"{len(right)}/5", why=why)


# ------------------------------------------------------------------ calendar: hours per weekday
def calendar_expected(world: World) -> dict[str, float]:
    """weekday -> hours of timed meetings over the quarter."""
    minutes: dict[str, float] = {day: 0.0 for day in WEEKDAYS}
    lo, hi = world.quarter
    for event in world.events:
        if event.all_day or not (lo <= event.start.date() <= hi):
            continue
        minutes[WEEKDAYS[event.start.weekday()]] += (event.end - event.start).total_seconds() / 60.0
    return {day: round(value / 60.0, 4) for day, value in minutes.items()}


def _calendar_question(world: World) -> str:
    lo, hi = world.quarter
    return (f"How many hours of meetings do I have on each day of the week, Monday through Sunday, from "
            f"{_d(lo)} through {_d(hi)}? Add up the scheduled length of every timed event on my calendar "
            f"in that range (all-day events are not meetings) and give the total hours for each weekday.")


def _calendar_score(answer: str, world: World) -> Score:
    want = calendar_expected(world)
    aliases = {day: (day, day[:3]) for day in WEEKDAYS}
    got = parse.segments(answer, aliases)
    right, wrong = 0, []
    for day, hours in want.items():
        value = parse.hours(got.get(day, "")) if day in got else None
        if value is None and hours == 0.0 and day not in got:
            right += 1          # "nothing on Sundays" by leaving Sunday out
            continue
        if value is not None and abs(value - hours) <= HOURS_TOLERANCE:
            right += 1
        else:
            wrong.append(f"{day} {hours:g} (read {value if value is not None else 'nothing'})")
    return Score(exact=right == 7, got=f"{right}/7",
                 why="" if right == 7 else "wrong: " + "; ".join(wrong))


# ------------------------------------------------------------------ files: the largest per type
def files_expected(world: World) -> dict[str, list[str]]:
    """type -> the basenames of its 10 largest files, largest first."""
    out: dict[str, list[str]] = {}
    for ext in FILE_TYPES:
        mine = sorted(((size, path) for size, path in world.files if path.endswith("." + ext)),
                      key=lambda row: (-row[0], row[1]))
        out[ext] = [path.rsplit("/", 1)[1] for _size, path in mine[:10]]
    return out


def _files_question(world: World) -> str:
    return (f"{FILES_INDEX} lists every file in my ~/Household folder, one per line: the size in bytes, a "
            f"tab, then the path. What are the 10 largest .jpg files, the 10 largest .pdf files and the 10 "
            f"largest .mp4 files? Give the file names for each type.")


def _files_score(answer: str, world: World) -> Score:
    want = files_expected(world)
    every = {path.rsplit("/", 1)[1] for _size, path in world.files}
    named = {name for name in parse.file_names(answer) if name in every}
    right, notes = 0, []
    for ext, names in want.items():
        mine = {n for n in named if n.endswith("." + ext)}
        hit = len(set(names) & mine)
        # All ten, and not buried in a dump: a reply listing every jpg
        # contains the right ten too.
        if hit == 10 and len(mine) <= 12:
            right += 1
        else:
            notes.append(f".{ext} {hit}/10 of the largest named" + (f", {len(mine)} named in all" if len(mine) > 12 else ""))
    return Score(exact=right == len(want), got=f"{right}/{len(want)} types", why="; ".join(notes))


# ------------------------------------------------------------------ telemetry: failures per tool
def telemetry_expected(world: World) -> dict[str, int]:
    """tool -> failed calls in the asked week; every tool, zeros too."""
    lo, hi = world.telemetry_window
    out: dict[str, int] = {}
    for row in world.telemetry:
        out.setdefault(row["tool"], 0)
        day = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").date()
        if lo <= day <= hi and not row["ok"]:
            out[row["tool"]] += 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _telemetry_question(world: World) -> str:
    lo, hi = world.telemetry_window
    return (f"{TELEMETRY_LOG} is a log of my tool calls, one JSON object per line (ts in UTC, tool, ok). How "
            f"many calls failed for each tool from {_d(lo)} through {_d(hi)} (UTC dates, inclusive)? Give "
            f"the exact count for every tool that failed at least once in that range.")


def _telemetry_score(answer: str, world: World) -> Score:
    want = telemetry_expected(world)
    aliases = {tool: (tool,) for tool in want}
    got = parse.segments(answer, aliases)
    wrong = []
    for tool, n in want.items():
        value = parse.first_number(got[tool]) if tool in got else None
        if n == 0:
            if value not in (None, 0.0):
                wrong.append(f"{tool} 0 (read {value:g})")
        elif value != n:
            wrong.append(f"{tool} {n} (read {'nothing' if value is None else f'{value:g}'})")
    total = len(want)
    return Score(exact=not wrong, got=f"{total - len(wrong)}/{total}", why="wrong: " + "; ".join(wrong) if wrong else "")


# ------------------------------------------------------------------ per item: each sender's latest
def latest_expected(world: World) -> dict[str, date]:
    """address -> the UTC date of their newest message, for the 25 named."""
    newest: dict[str, date] = defaultdict(lambda: date.min)
    for m in world.mail:
        addr = m["from"].split("<")[1].rstrip(">")
        newest[addr] = max(newest[addr], m["date"].astimezone(timezone.utc).date())
    return {s.address: newest[s.address] for s in world.named}


def _latest_question(world: World) -> str:
    names = "\n".join(f"- {s.name} <{s.address}>" for s in world.named)
    return (f"For each of these 25 senders, what is the date (UTC) of the most recent email I have from them? "
            f"Look through all my mail, not just this month, and give one date per sender.\n{names}")


def _latest_score(answer: str, world: World) -> Score:
    want = latest_expected(world)
    aliases = _sender_aliases(world)
    got = parse.segments(answer, aliases)
    wrong = []
    for addr, day in want.items():
        value = parse.first_date(got[addr], anchor=world.anchor) if addr in got else None
        if value != day:
            wrong.append(f"{addr} {day} (read {value or 'nothing'})")
    return Score(exact=not wrong, got=f"{len(want) - len(wrong)}/{len(want)}",
                 why=("wrong: " + "; ".join(wrong[:6]) + (f" and {len(wrong) - 6} more" if len(wrong) > 6 else ""))
                 if wrong else "")


CASES: tuple[CodeFirstCase, ...] = (
    CodeFirstCase("mail/top-senders-30-days", "mail", "rank", _mail_top_question, mail_top_expected,
                  _mail_top_score, reads=("mail_search",)),
    CodeFirstCase("calendar/hours-per-weekday", "calendar", "aggregate", _calendar_question, calendar_expected,
                  _calendar_score, reads=("cal_list",)),
    CodeFirstCase("files/largest-per-type", "files", "top-n", _files_question, files_expected,
                  _files_score, reads=("read_file",)),
    CodeFirstCase("telemetry/failures-per-tool", "telemetry", "window", _telemetry_question, telemetry_expected,
                  _telemetry_score, reads=("read_file",)),
    CodeFirstCase("mail/latest-per-sender", "mail", "per-item", _latest_question, latest_expected,
                  _latest_score, reads=("mail_search",)),
)


def by_id(case_id: str) -> CodeFirstCase | None:
    return next((c for c in CASES if c.id == case_id), None)


__all__ = ["CASES", "FILE_TYPES", "HOURS_TOLERANCE", "WEEKDAYS", "CodeFirstCase", "Score", "by_id",
           "calendar_expected", "files_expected", "latest_expected", "mail_top_expected", "telemetry_expected"]
