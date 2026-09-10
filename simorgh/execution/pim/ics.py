"""iCalendar (RFC 5545), the part a calendar reader actually needs.

Written rather than imported, because `icalendar` is a pip dependency
for something that is a line-folding rule, a date format and a
key-value parser -- and adding one would mean the calendar half of this
domain does not work until somebody installs it.

What this handles: line unfolding, parameter parsing (`TZID`, `VALUE`),
the three DATE-TIME forms (floating, UTC, TZID), all-day DATE values,
escaped text, VEVENT and VTODO, and the two recurrence rules that
account for nearly every repeating event a person actually has --
daily and weekly with BYDAY, with COUNT/UNTIL and EXDATE honoured.

What it does not: VTIMEZONE definitions (the system tz database is used
instead, via `zoneinfo`), monthly/yearly BYSETPOS, and RDATE. An event
whose rule is not expanded is still returned once at its DTSTART with
`recurrence` set, so it is visible and labelled rather than silently
missing -- the failure mode that matters is a calendar that quietly
drops your Tuesday standup, not one that shows it without every
instance.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from .api import Event, Task

#: RFC 5545 folds long lines by inserting CRLF + one space or tab.
_FOLD = re.compile(r"\r?\n[ \t]")

_ESCAPES = ((r"\\n", "\n"), (r"\\N", "\n"), (r"\\,", ","), (r"\;", ";"), (r"\\\\", "\\"))

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

#: An expansion bound. A rule with no COUNT and no UNTIL is infinite,
#: and a window query still has to terminate.
MAX_INSTANCES = 500


def unfold(text: str) -> list[str]:
    return [line for line in _FOLD.sub("", text or "").splitlines() if line.strip()]


def _unescape(value: str) -> str:
    for pattern, replacement in _ESCAPES:
        value = re.sub(pattern, replacement.replace("\\", "\\\\"), value)
    return value


def parse_line(line: str) -> tuple[str, dict[str, str], str]:
    """`DTSTART;TZID=Europe/London:20260910T150000` ->
    `("DTSTART", {"TZID": "Europe/London"}, "20260910T150000")`.

    The split is on the first colon *outside* a quoted parameter value,
    because `CN="Smith, John:esq"` is legal and a naive `split(":", 1)`
    turns that into a property nobody can read.
    """
    in_quotes = False
    for index, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ":" and not in_quotes:
            head, value = line[:index], line[index + 1:]
            break
    else:
        return line.strip().upper(), {}, ""

    parts: list[str] = []
    current = ""
    in_quotes = False
    for char in head:
        if char == '"':
            in_quotes = not in_quotes
            continue
        if char == ";" and not in_quotes:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)

    name = parts[0].strip().upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, _, param_value = part.partition("=")
        if key:
            params[key.strip().upper()] = param_value.strip()
    return name, params, value


def _zone(tzid: str):
    if not tzid:
        return None
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tzid)
    except Exception:  # noqa: BLE001 -- an unknown tz is floating time, not a parse failure
        return None


def parse_datetime(value: str, params: dict[str, str]) -> tuple[datetime | None, bool]:
    """`(value, all_day)`.

    An all-day event has no timezone at all. Treating it as midnight UTC
    moves it a day for anyone west of Greenwich, which is the classic
    calendar bug and the one this creator would see every time.
    """
    value = (value or "").strip()
    if not value:
        return None, False
    if params.get("VALUE", "").upper() == "DATE" or (len(value) == 8 and "T" not in value):
        try:
            parsed = datetime.strptime(value, "%Y%m%d")
        except ValueError:
            return None, False
        return parsed, True
    utc = value.endswith("Z")
    stripped = value[:-1] if utc else value
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            parsed = datetime.strptime(stripped, fmt)
        except ValueError:
            continue
        if utc:
            return parsed.replace(tzinfo=timezone.utc), False
        zone = _zone(params.get("TZID", ""))
        return (parsed.replace(tzinfo=zone) if zone else parsed), False
    return None, False


def parse_rrule(value: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (value or "").split(";"):
        key, _, val = part.partition("=")
        if key:
            out[key.strip().upper()] = val.strip()
    return out


def expand(start: datetime, rule: dict[str, str], *, window_start: datetime,
           window_end: datetime, exdates=()) -> list[datetime]:
    """Occurrences of `start` under `rule` that fall in the window.

    Daily and weekly only. Anything else returns `[start]`, so the event
    appears once and labelled rather than vanishing -- a calendar that
    silently drops your Tuesday standup is worse than one that shows it
    without every instance.
    """
    freq = rule.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY"):
        return [start]
    try:
        interval = max(1, int(rule.get("INTERVAL", "1")))
    except ValueError:
        interval = 1
    count = None
    if rule.get("COUNT"):
        try:
            count = int(rule["COUNT"])
        except ValueError:
            count = None
    until, _ = parse_datetime(rule.get("UNTIL", ""), {}) if rule.get("UNTIL") else (None, False)
    if until is not None and until.tzinfo is None and start.tzinfo is not None:
        until = until.replace(tzinfo=start.tzinfo)

    days = [_WEEKDAYS[d] for d in rule.get("BYDAY", "").split(",") if d in _WEEKDAYS]
    excluded = {_key(d) for d in exdates}

    out: list[datetime] = []
    emitted = 0
    cursor = start
    step = timedelta(days=interval) if freq == "DAILY" else timedelta(weeks=interval)

    for _ in range(MAX_INSTANCES):
        if until is not None and cursor > until:
            break
        if count is not None and emitted >= count:
            break
        instances = [cursor]
        if freq == "WEEKLY" and days:
            monday = cursor - timedelta(days=cursor.weekday())
            instances = [monday + timedelta(days=offset) for offset in sorted(days)]
        for instance in instances:
            if instance < start:
                continue
            if until is not None and instance > until:
                continue
            if count is not None and emitted >= count:
                break
            emitted += 1
            if _key(instance) in excluded:
                continue
            if window_start <= instance < window_end:
                out.append(instance)
        if cursor > window_end:
            break
        cursor = cursor + step
    return out


def _key(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def _blocks(lines: list[str], kind: str) -> list[list[tuple[str, dict, str]]]:
    """Every `BEGIN:<kind>` .. `END:<kind>` run, already parsed.

    Nesting matters: a VEVENT may contain a VALARM, and a naive scan for
    `END:` would close the event at the alarm's end and lose everything
    after it.
    """
    out: list[list[tuple[str, dict, str]]] = []
    current: list[tuple[str, dict, str]] | None = None
    depth = 0
    for line in lines:
        name, params, value = parse_line(line)
        if name == "BEGIN" and value.strip().upper() == kind:
            current, depth = [], 0
            continue
        if current is None:
            continue
        if name == "BEGIN":
            depth += 1
        elif name == "END":
            if value.strip().upper() == kind and depth == 0:
                out.append(current)
                current = None
                continue
            depth = max(0, depth - 1)
        current.append((name, params, value))
    return out


def parse_events(text: str, *, calendar: str = "", window: tuple[datetime, datetime] | None = None
                 ) -> list[Event]:
    """Every VEVENT in `text`, recurrences expanded into `window`."""
    events: list[Event] = []
    for block in _blocks(unfold(text), "VEVENT"):
        fields: dict[str, tuple[dict, str]] = {}
        exdates: list[datetime] = []
        attendees: list[str] = []
        for name, params, value in block:
            if name == "EXDATE":
                for piece in value.split(","):
                    parsed, _ = parse_datetime(piece, params)
                    if parsed is not None:
                        exdates.append(parsed)
            elif name == "ATTENDEE":
                attendees.append(_address(value))
            else:
                fields[name] = (params, value)

        start_params, start_value = fields.get("DTSTART", ({}, ""))
        start, all_day = parse_datetime(start_value, start_params)
        if start is None:
            continue
        end_params, end_value = fields.get("DTEND", ({}, ""))
        end, _ = parse_datetime(end_value, end_params)
        if end is None and "DURATION" in fields:
            end = start + parse_duration(fields["DURATION"][1])

        summary = _unescape(fields.get("SUMMARY", ({}, ""))[1])
        base = dict(
            uid=fields.get("UID", ({}, ""))[1] or f"{summary}-{_key(start)}",
            summary=summary,
            location=_unescape(fields.get("LOCATION", ({}, ""))[1]),
            description=_unescape(fields.get("DESCRIPTION", ({}, ""))[1]),
            calendar=calendar, all_day=all_day, attendees=tuple(attendees),
            organizer=_address(fields.get("ORGANIZER", ({}, ""))[1]),
            status=(fields.get("STATUS", ({}, ""))[1] or "confirmed").lower(),
        )

        rrule_value = fields.get("RRULE", ({}, ""))[1]
        if not rrule_value or window is None:
            events.append(Event(start=start, end=end, recurrence=rrule_value, **base))
            continue

        rule = parse_rrule(rrule_value)
        length = (end - start) if end is not None else None
        for occurrence in expand(start, rule, window_start=window[0], window_end=window[1],
                                 exdates=exdates):
            events.append(Event(start=occurrence,
                                end=(occurrence + length) if length is not None else None,
                                recurrence=rrule_value, **base))
    events.sort(key=lambda event: (event.start.replace(tzinfo=None), event.summary))
    return events


def parse_duration(value: str) -> timedelta:
    """`PT1H30M`, `P1D`. An unparseable duration is an hour, which is
    wrong in a small way rather than a crash in a large one."""
    match = re.fullmatch(r"[+-]?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
                         (value or "").strip().upper())
    if not match:
        return timedelta(hours=1)
    weeks, days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    total = timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)
    return total or timedelta(hours=1)


def _address(value: str) -> str:
    value = (value or "").strip()
    if value.upper().startswith("MAILTO:"):
        return value[7:]
    return value


def parse_tasks(text: str, *, list_name: str = "") -> list[Task]:
    tasks: list[Task] = []
    for block in _blocks(unfold(text), "VTODO"):
        fields = {name: (params, value) for name, params, value in block}
        due_params, due_value = fields.get("DUE", ({}, ""))
        due, _ = parse_datetime(due_value, due_params)
        status = (fields.get("STATUS", ({}, ""))[1] or "").upper()
        try:
            priority = int(fields.get("PRIORITY", ({}, "0"))[1] or 0)
        except ValueError:
            priority = 0
        tasks.append(Task(
            uid=fields.get("UID", ({}, ""))[1],
            summary=_unescape(fields.get("SUMMARY", ({}, ""))[1]),
            due=due, done=status in ("COMPLETED", "CANCELLED"), priority=priority,
            list_name=list_name, notes=_unescape(fields.get("DESCRIPTION", ({}, ""))[1]),
        ))
    return tasks


__all__ = ["MAX_INSTANCES", "expand", "parse_datetime", "parse_duration", "parse_events",
           "parse_line", "parse_rrule", "parse_tasks", "unfold"]
