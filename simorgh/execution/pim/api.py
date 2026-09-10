"""The domain objects a `pim` connector returns.

The point of these is that `cal_list` renders one `Event` whether it
came from Fastmail over CalDAV, from Google, or from a fake in a test.
A tool that touched vendor JSON would need a branch per provider, and
the branch nobody has an account for is the branch nobody tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone


@dataclass(frozen=True)
class Account:
    """One configured mailbox or calendar."""

    name: str                    # "fastmail", "work"
    kind: str                    # caldav | imap | google | msgraph
    url: str = ""
    username: str = ""
    #: The vault credential id (`imap:fastmail`). The *value* never
    #: appears on this object, and never in a log or a ToolResult.
    cred_id: str = ""
    privacy: str = "personal"
    calendars: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "url": self.url,
                "username": self.username, "cred_id": self.cred_id, "privacy": self.privacy,
                "calendars": list(self.calendars), "folders": list(self.folders)}


@dataclass(frozen=True)
class Calendar:
    id: str
    name: str
    url: str = ""
    colour: str = ""
    read_only: bool = False


@dataclass(frozen=True)
class Event:
    uid: str
    summary: str
    start: datetime
    end: datetime | None = None
    location: str = ""
    description: str = ""
    calendar: str = ""
    #: True for a date-only event. An all-day event has no timezone at
    #: all, and treating it as midnight UTC moves it a day for anyone
    #: west of Greenwich -- which is most of the world and all of this
    #: creator's timezone.
    all_day: bool = False
    attendees: tuple[str, ...] = ()
    organizer: str = ""
    status: str = "confirmed"
    recurrence: str = ""

    @property
    def duration(self) -> timedelta:
        if self.end is None:
            return timedelta(hours=1) if not self.all_day else timedelta(days=1)
        return self.end - self.start

    def render(self, *, with_date: bool = True) -> str:
        if self.all_day:
            when = self.start.strftime("%a %d %b") if with_date else "all day"
            when += " (all day)"
        else:
            when = self.start.strftime("%a %d %b %H:%M") if with_date else self.start.strftime("%H:%M")
            if self.end is not None:
                when += self.end.strftime("-%H:%M")
        line = f"{when}  {self.summary or '(no title)'}"
        if self.location:
            line += f"  @ {self.location}"
        return line


@dataclass(frozen=True)
class MailMessage:
    """A message. `body` is deliberately optional and empty by default:
    headers are `personal`, bodies are `sensitive`
    (platform-connectors-design.md section 10), and a search that pulled
    every body back would make the cheap operation the exposing one."""

    uid: str
    folder: str
    subject: str
    sender: str
    to: tuple[str, ...] = ()
    date: datetime | None = None
    snippet: str = ""
    body: str = ""
    flags: tuple[str, ...] = ()
    size: int = 0
    has_attachments: bool = False
    account: str = ""

    @property
    def unread(self) -> bool:
        return "\\Seen" not in self.flags

    def render(self) -> str:
        when = self.date.strftime("%d %b %H:%M") if self.date else "(no date)"
        mark = "  " if not self.unread else "* "
        line = f"{mark}{when}  {self.sender[:40]:40}  {self.subject or '(no subject)'}"
        if self.has_attachments:
            line += "  [attachment]"
        return line


@dataclass(frozen=True)
class Task:
    uid: str
    summary: str
    due: datetime | None = None
    done: bool = False
    priority: int = 0
    list_name: str = ""
    notes: str = ""


@dataclass
class FreeBusy:
    """Busy intervals, merged. What `cal_find_time` subtracts from."""

    busy: list[tuple[datetime, datetime]] = field(default_factory=list)

    def add(self, start: datetime, end: datetime) -> None:
        if end > start:
            self.busy.append((start, end))

    def merged(self) -> list[tuple[datetime, datetime]]:
        if not self.busy:
            return []
        out: list[tuple[datetime, datetime]] = []
        for start, end in sorted(self.busy):
            if out and start <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], end))
            else:
                out.append((start, end))
        return out


def as_utc(value: datetime) -> datetime:
    """A naive datetime is local time -- that is what a calendar server
    means by one without a TZID, and what a person means when they say
    "3pm"."""
    if value.tzinfo is None:
        return value.astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def day_bounds(day: date, *, tz=None) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return start, start + timedelta(days=1)


__all__ = ["Account", "Calendar", "Event", "FreeBusy", "MailMessage", "Task", "as_utc",
           "day_bounds"]
