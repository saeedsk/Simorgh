""""tomorrow at 3" -> a datetime.

`dateparser` handles far more than this and is a pip dependency for
something a reminder tool needs to do on every call. What a person
actually types into a reminder is a small, closed set of shapes, and
each of them is a few lines. The rule when a phrase is not one of them
is to say so and ask -- never to guess, because a reminder that fires on
the wrong day is worse than one that was never set.

Local time throughout, because "3pm" means three in the afternoon where
the person is standing.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}

_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
}

_DELAY = re.compile(r"^(?:in\s+)?(\d+(?:\.\d+)?)\s*([a-z]+)$", re.I)
_TIME = re.compile(
    r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b(?!\s*(?:days?|weeks?|hours?|mins?|minutes?))",
    re.I)
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?$")


class Ambiguous(ValueError):
    """The phrase could mean more than one thing, or nothing. Carries
    the question to put to the person rather than a parser error."""


def parse_delay(text: str) -> float | None:
    """`"20m"`, `"in 2 hours"` -> seconds. None when it is not a delay."""
    match = _DELAY.match((text or "").strip())
    if not match:
        return None
    unit = _UNITS.get(match.group(2).lower())
    return float(match.group(1)) * unit if unit else None


def _time_of_day(text: str) -> tuple[int, int] | None:
    match = _TIME.search(text or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    elif not meridiem and match.group(2) is None and hour <= 12:
        # "at 3" with no am/pm and no minutes. Waking someone at three
        # in the morning because they meant the afternoon is the exact
        # failure this refuses to guess at.
        if hour < 7:
            raise Ambiguous(
                f"does {hour} mean {hour}am or {hour}pm? Say \"{hour}am\" or \"{hour}pm\".")
        hour = hour + 12 if hour < 7 else hour
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour, minute


def parse_when(text: str, *, now: datetime | None = None) -> datetime:
    """A phrase to an absolute local datetime, or `Ambiguous`.

    Handles: a bare delay ("20m", "in 2 hours"), "today"/"tonight"/
    "tomorrow" with an optional time, a weekday ("friday", "next
    tuesday"), an ISO date, and a bare time ("at 3pm") meaning the next
    time it is that o'clock.
    """
    now = now or datetime.now()
    raw = " ".join((text or "").split()).strip().lower()
    if not raw:
        raise Ambiguous("when should this happen?")

    delay = parse_delay(raw)
    if delay is not None:
        return now + timedelta(seconds=delay)

    iso = _ISO.match(raw)
    if iso:
        year, month, day = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        hour = int(iso.group(4) or 9)
        minute = int(iso.group(5) or 0)
        return datetime(year, month, day, hour, minute)

    when = _time_of_day(raw)
    base: date | None = None

    if raw.startswith("tomorrow") or " tomorrow" in raw:
        base = now.date() + timedelta(days=1)
    elif raw.startswith("today") or raw.startswith("tonight") or " today" in raw:
        base = now.date()
        if raw.startswith("tonight") and when is None:
            when = (20, 0)
    else:
        next_week = raw.startswith("next ")
        for name, index in _WEEKDAYS.items():
            if re.search(rf"\b{name}\b", raw):
                ahead = (index - now.weekday()) % 7
                # "friday" said on a Friday means the one coming, not
                # the one already half over.
                if ahead == 0:
                    ahead = 7
                if next_week and ahead <= 0:
                    ahead += 7
                base = now.date() + timedelta(days=ahead)
                break

    if base is None and when is None:
        raise Ambiguous(
            f"I could not turn {text!r} into a time. Try \"20m\", \"tomorrow 9am\", "
            "\"friday at 15:00\" or \"2026-10-01 09:00\".")

    if base is None:
        # A bare time means the next time it is that o'clock.
        hour, minute = when
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)

    hour, minute = when or (9, 0)
    return datetime(base.year, base.month, base.day, hour, minute)


def parse_range(text: str, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """A calendar window: "today", "tomorrow", "this week", "next week",
    "7 days", or an ISO date. Defaults to today."""
    now = now or datetime.now()
    raw = " ".join((text or "today").split()).strip().lower()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if raw in ("today", ""):
        return midnight, midnight + timedelta(days=1)
    if raw == "tomorrow":
        return midnight + timedelta(days=1), midnight + timedelta(days=2)
    if raw in ("this week", "week"):
        start = midnight - timedelta(days=now.weekday())
        return start, start + timedelta(days=7)
    if raw == "next week":
        start = midnight - timedelta(days=now.weekday()) + timedelta(days=7)
        return start, start + timedelta(days=7)
    if raw in ("this month", "month"):
        start = midnight.replace(day=1)
        following = (start + timedelta(days=32)).replace(day=1)
        return start, following

    seconds = parse_delay(raw)
    if seconds is not None:
        return midnight, midnight + timedelta(seconds=max(seconds, 86400))

    iso = _ISO.match(raw)
    if iso:
        day = datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        return day, day + timedelta(days=1)

    raise Ambiguous(
        f"I could not turn {text!r} into a date range. Try \"today\", \"this week\", "
        "\"7 days\" or an ISO date.")


__all__ = ["Ambiguous", "parse_delay", "parse_range", "parse_when"]
