"""Reading an answer the way a person would (stage 19 item 8).

A reply is prose, a list or a table, in whatever words the model chose.
The scoring must not care which -- a test that pins the format fails
when the model gets better -- so an answer is read as **mentions**: each
thing the question is about (a sender, a weekday, a tool, a file) found
by any of its names, and the **segment** after it, up to the next
mention of anything the world knows or the end of the line, holding its
value. "1. Daily Deals <deals@shopnest.example> -- 97 messages",
"Daily Deals: 97" and "| deals@shopnest.example | 97 |" all read the same.
"""

from __future__ import annotations

import re
from datetime import date

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"), start=1)}


def _pattern(alias: str) -> str:
    return r"(?<![\w@.])" + re.escape(alias) + r"(?![\w@])"


def mentions(text: str, aliases: dict[str, tuple[str, ...]]) -> list[tuple[int, int, str]]:
    """Every (start, end, key) where one of a key's aliases appears,
    case-insensitively and as a whole word, longest alias first and
    never overlapping."""
    found: list[tuple[int, int, str]] = []
    ordered = sorted(((alias, key) for key, names in aliases.items() for alias in names if alias),
                     key=lambda pair: -len(pair[0]))
    taken: list[tuple[int, int]] = []
    for alias, key in ordered:
        for match in re.finditer(_pattern(alias), text, flags=re.IGNORECASE):
            start, end = match.span()
            if any(start < b and end > a for a, b in taken):
                continue
            taken.append((start, end))
            found.append((start, end, key))
    found.sort()
    # "Name <address>" is ONE mention of one key, not two.
    merged: list[tuple[int, int, str]] = []
    for start, end, key in found:
        if merged and merged[-1][2] == key and re.fullmatch(r"[\s<(\[\"']*", text[merged[-1][1]:start]):
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]), key)
            continue
        merged.append((start, end, key))
    return merged


def segments(text: str, aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """key -> the text after its first mention that holds a value (a
    digit): up to the next mention or the end of the line, or -- when
    that holds no digit -- on to the next line, still never past the
    next mention. "Monday through Sunday, in hours:" and then a list
    reads the list, not the preamble."""
    found = mentions(text, aliases)
    out: dict[str, str] = {}
    for index, (_start, end, key) in enumerate(found):
        if key in out and re.search(r"\d", out[key]):
            continue
        limit = found[index + 1][0] if index + 1 < len(found) else len(text)
        line_end = text.find("\n", end)
        line_end = limit if line_end < 0 else min(line_end, limit)
        piece = text[end:line_end]
        if not re.search(r"\d", piece):
            following = text.find("\n", line_end + 1)
            piece = text[end:min(limit, following if following >= 0 else len(text))]
        out[key] = piece
    return out


def order(text: str, aliases: dict[str, tuple[str, ...]]) -> list[str]:
    """Keys in order of first mention."""
    seen: list[str] = []
    for _s, _e, key in mentions(text, aliases):
        if key not in seen:
            seen.append(key)
    return seen


_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+")
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\d])")


def first_number(segment: str) -> float | None:
    """The first number in a segment, ignoring addresses, `1,234` read
    as 1234."""
    cleaned = _EMAIL.sub(" ", segment)
    match = _NUMBER.search(cleaned)
    if not match:
        return None
    whole = match.group(1).replace(",", "")
    return float(f"{whole}.{match.group(2)}") if match.group(2) else float(whole)


_HM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hrs?|hours?)\b(?:\s*(?:and\s*)?(\d+)\s*(?:m|mins?|minutes?)\b)?",
                 re.IGNORECASE)
_MIN_ONLY = re.compile(r"(\d+)\s*(?:m|mins?|minutes?)\b", re.IGNORECASE)
_CLOCK = re.compile(r"(?<![\d:])(\d{1,3}):([0-5]\d)(?![\d:])")


def hours(segment: str) -> float | None:
    """Hours from "12.5", "12.5 hours", "12 h 30 m", "12 hours and 30
    minutes", "750 minutes" or "12:30"."""
    match = _HM.search(segment)
    if match:
        return float(match.group(1)) + (int(match.group(2)) / 60.0 if match.group(2) else 0.0)
    match = _CLOCK.search(segment)
    if match:
        return int(match.group(1)) + int(match.group(2)) / 60.0
    match = _MIN_ONLY.search(segment)
    number = first_number(segment)
    if match and (number is None or float(match.group(1)) == number):
        return int(match.group(1)) / 60.0
    return number


_ISO = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_DAY_MONTH = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?[\s-]+(?:of\s+)?([A-Za-z]{3,9})\.?,?(?:[\s-]+(\d{4}))?")
_MONTH_DAY = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?")


def first_date(segment: str, *, anchor: date) -> date | None:
    """The first date in a segment: ISO, "3 Oct 2026", "3rd of October",
    "October 3, 2026", "Oct 3". A date with no year is the latest one on
    or before `anchor` -- every date these questions ask for is past."""
    best: tuple[int, date] | None = None

    def consider(pos: int, value: date | None) -> None:
        nonlocal best
        if value is not None and (best is None or pos < best[0]):
            best = (pos, value)

    for match in _ISO.finditer(segment):
        consider(match.start(), _safe(int(match.group(1)), int(match.group(2)), int(match.group(3))))
    for match in _DAY_MONTH.finditer(segment):
        month = _MONTHS.get(match.group(2)[:3].lower())
        if month and match.group(2).lower() in _month_words(month):
            consider(match.start(), _dated(int(match.group(1)), month, match.group(3), anchor))
    for match in _MONTH_DAY.finditer(segment):
        month = _MONTHS.get(match.group(1)[:3].lower())
        if month and match.group(1).lower() in _month_words(month):
            consider(match.start(), _dated(int(match.group(2)), month, match.group(3), anchor))
    return best[1] if best else None


def _month_words(month: int) -> tuple[str, ...]:
    full = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
            "november", "december")[month - 1]
    return (full, full[:3]) + (("sept",) if month == 9 else ())


def _dated(day: int, month: int, year: str | None, anchor: date) -> date | None:
    if year:
        return _safe(int(year), month, day)
    value = _safe(anchor.year, month, day)
    if value is not None and value > anchor:
        value = _safe(anchor.year - 1, month, day)
    return value


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


_FILE_TOKEN = re.compile(r"[\w.\-]+\.([A-Za-z0-9]{2,5})\b")


def file_names(text: str) -> list[str]:
    """Every file basename mentioned, paths cut to their last part."""
    return [match.group(0) for match in _FILE_TOKEN.finditer(text.replace("/", " ").replace("\\", " "))]


__all__ = ["file_names", "first_date", "first_number", "hours", "mentions", "order", "segments"]
