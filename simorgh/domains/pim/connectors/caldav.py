"""CalDAV over stdlib HTTP.

CalDAV is WebDAV plus two XML report types, and a calendar reader needs
exactly one of them: `calendar-query` with a time-range filter, which
returns iCalendar text that `ics.py` already parses. That is a `REPORT`
request with an XML body -- `urllib` does both -- so the whole client is
this file and no pip install.

Discovery is supported but optional. Given a collection URL (what every
provider shows in its settings page, and what a person will paste), it
queries it directly. Given a principal or root URL, it walks
`current-user-principal` -> `calendar-home-set` -> the collections
underneath, which is the standard three-hop dance.

Authentication is HTTP Basic over HTTPS. Every major provider accepts
it with an app-specific password, which is the credential a person
should be using here anyway -- an app password can be revoked without
touching the account, and this code can never be asked for a second
factor.
"""

from __future__ import annotations

import base64
import socket
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree

from simorgh.contracts.connector import Budget, ConnectorStatus, missing_requirements

from ..api import Calendar, Event
from ..ics import parse_events

_DAV = "DAV:"
_CALDAV = "urn:ietf:params:xml:ns:caldav"
_NS = {"d": _DAV, "c": _CALDAV}

_PRINCIPAL_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
)
_HOME_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><c:calendar-home-set/></d:prop></d:propfind>"
)
_COLLECTIONS_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><d:resourcetype/><d:displayname/><d:current-user-privilege-set/></d:prop>"
    "</d:propfind>"
)


def _query_body(start: datetime, end: datetime) -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
        '<c:filter><c:comp-filter name="VCALENDAR">'
        '<c:comp-filter name="VEVENT">'
        f'<c:time-range start="{start.astimezone(timezone.utc).strftime(fmt)}" '
        f'end="{end.astimezone(timezone.utc).strftime(fmt)}"/>'
        "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
    )


class _Request(urllib.request.Request):
    def __init__(self, url: str, *, method: str, **kwargs) -> None:
        super().__init__(url, **kwargs)
        self._method = method

    def get_method(self) -> str:
        return self._method


class CalDavConnector:
    """One CalDAV account.

    Construction never raises and never opens a socket: a wrong URL or a
    missing password is something `probe()` reports, not something that
    stops Sim booting.
    """

    packages: tuple[str, ...] = ()   # stdlib only, by design

    def __init__(self, *, name: str, url: str, username: str = "", password: str = "",
                 calendars: tuple[str, ...] = (), timeout_s: float = 20.0,
                 opener=None, budget: Budget | None = None) -> None:
        self.name = name
        self.url = (url or "").rstrip("/")
        self.needs: tuple[str, ...] = (f"caldav:{name}",)
        self._username = username
        self._password = password
        self._calendars = calendars
        self._timeout = timeout_s
        self._opener = opener or urllib.request.urlopen
        # 240 requests an hour is far above one person reading their own
        # calendar and far below anything a provider would throttle.
        self._budget = budget or Budget(f"caldav:{name}", limit=240, window_s=3600.0)
        self._discovered: list[Calendar] | None = None

    # -- lifecycle -----------------------------------------------------------

    async def probe(self) -> ConnectorStatus:
        missing = list(missing_requirements(
            ("url", "username", "password"),
            {"url": bool(self.url), "username": bool(self._username),
             "password": bool(self._password)}))
        if missing:
            return ConnectorStatus(
                False,
                f"{self.name}: set the CalDAV url and username in [execution] pim_accounts, and "
                f"the password with `vault add caldav:{self.name} password`",
                tuple(missing))
        if not self.url.lower().startswith(("http://", "https://")):
            return ConnectorStatus(False, f"{self.name}: {self.url!r} is not an http(s) URL",
                                   ("url",))
        try:
            status, _, _ = await self._send("OPTIONS", self.url, body=None)
        except _CalDavError as exc:
            # The message is `str(exc)`, never the request: a URL can
            # carry a token in its path, and an exception string ends up
            # in a ToolResult and then in the Ledger.
            return ConnectorStatus(False, f"{self.name}: {exc}", ())
        if status in (401, 403):
            return ConnectorStatus(
                False,
                f"{self.name}: the server refused these credentials ({status}). Most providers "
                f"need an app-specific password here, not the account password.", ())
        if status >= 400:
            return ConnectorStatus(False, f"{self.name}: the server answered {status}", ())
        return ConnectorStatus(True, f"{self.name}: reachable at {self.url}")

    async def close(self) -> None:
        self._discovered = None

    # -- reading -------------------------------------------------------------

    async def calendars(self) -> list[Calendar]:
        if self._discovered is not None:
            return self._discovered
        home = await self._calendar_home()
        status, _, text = await self._send("PROPFIND", home, body=_COLLECTIONS_BODY, depth="1")
        found: list[Calendar] = []
        if status < 400 and text:
            for response in _findall(text, "d:response"):
                href = _text(response, "d:href")
                if not href or not _is_calendar(response):
                    continue
                name = _text(response, "d:propstat/d:prop/d:displayname") or href.rstrip("/").rsplit("/", 1)[-1]
                url = self._absolute(href)
                if self._calendars and name not in self._calendars:
                    continue
                found.append(Calendar(id=href, name=name, url=url,
                                      read_only=_is_read_only(response)))
        if not found:
            # A URL pointed straight at one collection is the common
            # case (it is what a settings page shows), and discovery
            # returning nothing for it must not mean "you have no
            # calendars".
            found = [Calendar(id=self.url, name=self.name, url=self.url)]
        self._discovered = found
        return found

    async def events(self, start: datetime, end: datetime) -> list[Event]:
        out: list[Event] = []
        for calendar in await self.calendars():
            status, _, text = await self._send(
                "REPORT", calendar.url, body=_query_body(start, end), depth="1")
            if status >= 400 or not text:
                continue
            for response in _findall(text, "d:response"):
                data = _text(response, "d:propstat/d:prop/c:calendar-data")
                if not data:
                    continue
                out.extend(parse_events(data, calendar=calendar.name, window=(start, end)))
        out.sort(key=lambda event: (event.start.replace(tzinfo=None), event.summary))
        return out

    # -- plumbing ------------------------------------------------------------

    async def _calendar_home(self) -> str:
        """The collection root. Falls back to the configured URL, which
        is right whenever a person pasted a collection URL directly."""
        status, _, text = await self._send("PROPFIND", self.url, body=_PRINCIPAL_BODY, depth="0")
        if status >= 400 or not text:
            return self.url
        principal = _first_href(text, "d:propstat/d:prop/d:current-user-principal/d:href")
        if not principal:
            return self.url
        status, _, text = await self._send("PROPFIND", self._absolute(principal),
                                           body=_HOME_BODY, depth="0")
        if status >= 400 or not text:
            return self.url
        home = _first_href(text, "d:propstat/d:prop/c:calendar-home-set/d:href")
        return self._absolute(home) if home else self.url

    def _absolute(self, href: str) -> str:
        if href.lower().startswith(("http://", "https://")):
            return href
        from urllib.parse import urljoin

        return urljoin(self.url + "/", href)

    async def _send(self, method: str, url: str, *, body: str | None, depth: str = "0"):
        import asyncio

        self._budget.take()
        headers = {"Content-Type": 'application/xml; charset="utf-8"', "Depth": depth,
                   "User-Agent": "simorgh/1.0"}
        if self._username or self._password:
            token = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"

        def _do():
            request = _Request(url, method=method, headers=headers,
                               data=body.encode("utf-8") if body else None)
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return (getattr(response, "status", 200), dict(getattr(response, "headers", {})),
                            response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                return int(exc.code), {}, ""
            except urllib.error.URLError as exc:
                raise _CalDavError(f"could not reach the server ({exc.reason})") from exc
            except (socket.timeout, TimeoutError) as exc:
                raise _CalDavError(f"the server did not answer in {self._timeout:.0f}s") from exc
            except ssl.SSLError as exc:
                raise _CalDavError(f"TLS failed ({exc.reason if hasattr(exc, 'reason') else exc})") from exc

        return await asyncio.to_thread(_do)


class _CalDavError(RuntimeError):
    """A transport problem, phrased for a person and carrying no URL."""


def _parse(text: str):
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None


def _findall(text: str, path: str) -> list:
    root = _parse(text)
    return list(root.findall(path, _NS)) if root is not None else []


def _text(element, path: str) -> str:
    found = element.find(path, _NS)
    return (found.text or "").strip() if found is not None else ""


def _first_href(text: str, path: str) -> str:
    for response in _findall(text, "d:response"):
        value = _text(response, path)
        if value:
            return value
    return ""


def _is_calendar(response) -> bool:
    resourcetype = response.find("d:propstat/d:prop/d:resourcetype", _NS)
    if resourcetype is None:
        return False
    return resourcetype.find("c:calendar", _NS) is not None


def _is_read_only(response) -> bool:
    privileges = response.find("d:propstat/d:prop/d:current-user-privilege-set", _NS)
    if privileges is None:
        return False
    granted = {p.tag.split("}")[-1] for p in privileges.iter() if p.tag.endswith("}privilege") is False}
    return "write" not in granted and "write-content" not in granted and bool(granted)


__all__ = ["CalDavConnector"]
