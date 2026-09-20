"""In-memory stand-ins for both connectors.

Every test in this domain drives one of these: **no test touches a real
account, network, or device**. They are not simplifications of the real
connectors -- they satisfy the same `Connector` protocol and return the
same domain dataclasses, so a tool exercised against a fake is
exercised against exactly the shape it will meet in production.

`FakeImap` goes one step further and is a fake *IMAP server*, plugged in
through `ImapConnector`'s `client_factory`. That way the real parsing
code -- the FETCH response shredding, the RFC 2047 subject decoding, the
multipart body walk -- is what runs in the tests, rather than being
skipped over by a fake that returns finished objects.
"""

from __future__ import annotations

import email.message
import email.utils
import imaplib
from datetime import datetime, timedelta, timezone

from simorgh.contracts.connector import ConnectorStatus

from ..api import Calendar, Event, MailMessage


class FakeCalDav:
    """A calendar with a fixed set of events."""

    packages: tuple[str, ...] = ()

    def __init__(self, name: str = "fake-caldav", events=None, *, ok: bool = True,
                 detail: str = "", missing: tuple[str, ...] = ()) -> None:
        self.name = name
        self.needs = (f"caldav:{name}",)
        self._events = list(events or [])
        self._status = ConnectorStatus(ok, detail or (f"{name}: ready" if ok else f"{name}: not configured"),
                                       missing)
        self.probes = 0
        self.closed = 0
        self.queries: list[tuple[datetime, datetime]] = []

    async def probe(self) -> ConnectorStatus:
        self.probes += 1
        return self._status

    async def close(self) -> None:
        self.closed += 1

    async def calendars(self) -> list[Calendar]:
        names = sorted({event.calendar for event in self._events if event.calendar}) or [self.name]
        return [Calendar(id=name, name=name, url=f"https://fake/{name}") for name in names]

    async def events(self, start: datetime, end: datetime) -> list[Event]:
        self.queries.append((start, end))
        out = [event for event in self._events if _overlaps(event, start, end)]
        out.sort(key=lambda event: (event.start.replace(tzinfo=None), event.summary))
        return out

    def add(self, event: Event) -> None:
        self._events.append(event)


def _overlaps(event: Event, start: datetime, end: datetime) -> bool:
    event_start = _naive(event.start)
    event_end = _naive(event.end) if event.end is not None else event_start + timedelta(hours=1)
    return event_start < _naive(end) and event_end > _naive(start)


def _naive(value: datetime) -> datetime:
    """Compare in one frame. Mixing aware and naive datetimes raises,
    and a fake that raises on a timezone is a fake that hides the bug it
    was meant to expose."""
    return value.replace(tzinfo=None) if value.tzinfo is None else \
        value.astimezone(timezone.utc).replace(tzinfo=None)


class FakeImapServer:
    """Speaks the slice of IMAP that `ImapConnector` uses, in the wire
    shapes `imaplib` would hand back -- byte literals, parenthesised
    FETCH rows and all."""

    #: Subclassing the real one on purpose. A fake that raises its own
    #: exception type would slip past the connector's `except
    #: imaplib.IMAP4.error` and prove nothing about the handling that
    #: actually runs in production.
    error = imaplib.IMAP4.error

    def __init__(self, messages=None, *, folders=("INBOX", "Archive"), login_fails: bool = False,
                 password: str = "") -> None:
        self.messages = list(messages or [])
        self._folders = list(folders)
        self._login_fails = login_fails
        self._password = password
        self.selected = ""
        self.logged_in = False
        self.closed = False
        self.commands: list[tuple] = []

    # -- imaplib surface -----------------------------------------------------

    def login(self, username: str, password: str):
        self.commands.append(("login", username))
        if self._login_fails or (self._password and password != self._password):
            # imaplib's own error string includes the whole LOGIN
            # command, password and all. Reproduced here on purpose: it
            # is what the connector must never let escape.
            raise FakeImapServer.error(
                f'LOGIN command error: BAD [b\'LOGIN "{username}" "{password}"\']')
        self.logged_in = True
        return "OK", [b"Logged in"]

    def list(self, directory='""', pattern="*"):
        rows = [f'(\\HasNoChildren) "/" "{name}"'.encode() for name in self._folders]
        return "OK", rows

    def select(self, mailbox="INBOX", readonly=False):
        name = mailbox.strip('"')
        self.commands.append(("select", name, readonly))
        if name not in self._folders:
            return "NO", [b"no such mailbox"]
        self.selected = name
        return "OK", [str(len(self._in(name))).encode()]

    def uid(self, command: str, *args):
        command = command.upper()
        self.commands.append((command,) + tuple(args))
        if command == "SEARCH":
            return "OK", [b" ".join(str(m["uid"]).encode() for m in self._matching(args[1:]))]
        if command == "FETCH":
            wanted = {int(x) for x in (args[0] or b"").split(b",") if x}
            spec = args[1] if len(args) > 1 else ""
            rows = []
            for message in self._in(self.selected):
                if message["uid"] not in wanted:
                    continue
                rows.append(self._row(message, full="RFC822" in spec and "HEADER" not in spec))
            return "OK", rows
        return "NO", [b"unsupported"]

    def close(self):
        self.selected = ""
        return "OK", [b"closed"]

    def logout(self):
        self.closed = True
        return "BYE", [b"bye"]

    # -- building wire responses ---------------------------------------------

    def _in(self, folder: str) -> list[dict]:
        return [m for m in self.messages if m.get("folder", "INBOX") == (folder or "INBOX")]

    def _matching(self, criteria) -> list[dict]:
        text = " ".join(str(c) for c in criteria).upper()
        out = self._in(self.selected)
        if "UNSEEN" in text:
            out = [m for m in out if "\\Seen" not in m.get("flags", [])]
        if "TEXT" in text:
            needle = str(criteria[-1]).strip('"').lower()
            out = [m for m in out
                   if needle in (m.get("subject", "") + m.get("from", "") + m.get("body", "")).lower()]
        return out

    def _row(self, message: dict, *, full: bool) -> tuple:
        flags = " ".join(message.get("flags", []))
        head = f'{message["uid"]} (UID {message["uid"]} RFC822.SIZE {message.get("size", 512)} FLAGS ({flags})'
        built = _build_message(message, headers_only=not full)
        return (head.encode(), built)


def _build_message(spec: dict, *, headers_only: bool) -> bytes:
    """A real RFC 5322 message, so the connector's real parser runs."""
    if spec.get("html") and not headers_only:
        outer = email.message.EmailMessage()
        outer["Subject"] = spec.get("subject", "")
        outer["From"] = spec.get("from", "")
        outer["To"] = ", ".join(spec.get("to", []) or [])
        outer["Date"] = email.utils.format_datetime(
            spec.get("date") or datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc))
        outer.set_content(spec.get("body", ""))
        outer.add_alternative(spec["html"], subtype="html")
        return outer.as_bytes()

    message = email.message.EmailMessage()
    message["Subject"] = spec.get("subject", "")
    message["From"] = spec.get("from", "")
    message["To"] = ", ".join(spec.get("to", []) or [])
    message["Date"] = email.utils.format_datetime(
        spec.get("date") or datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc))
    if spec.get("attachment"):
        message.set_content(spec.get("body", "") if not headers_only else "")
        message.add_attachment(b"binary", maintype="application", subtype="octet-stream",
                               filename=spec["attachment"])
        if headers_only:
            # Headers-only fetches still carry Content-Type, which is
            # how the attachment flag survives to a search result.
            header_only = email.message.EmailMessage()
            for key in ("Subject", "From", "To", "Date"):
                if message[key]:
                    header_only[key] = message[key]
            header_only["Content-Type"] = message["Content-Type"]
            return header_only.as_bytes()
        return message.as_bytes()
    if headers_only:
        return message.as_bytes()
    message.set_content(spec.get("body", ""))
    return message.as_bytes()


def FakeImap(name: str = "fake-imap", messages=None, **kwargs):
    """An `ImapConnector` wired to a `FakeImapServer` -- the real
    connector, the real parsing, a fake socket."""
    from .imap import ImapConnector

    server = FakeImapServer(messages=messages, **kwargs)
    connector = ImapConnector(name=name, host="imap.fake", username="me@fake",
                              password=kwargs.get("password") or "app-password",
                              client_factory=lambda: server)
    connector.server = server
    return connector


__all__ = ["FakeCalDav", "FakeImap", "FakeImapServer"]
