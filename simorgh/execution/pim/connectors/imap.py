"""IMAP over stdlib `imaplib` and `email`.

`imapclient` is the nicer library, and `imaplib` is already here. What
this needs from IMAP is a small surface -- list folders, search, fetch
headers, fetch one body -- and the awkward parts of `imaplib` (byte
literals, the parenthesised FETCH response, modified-UTF-7 folder
names) are each a few lines. So mail works on a fresh machine with a
password and nothing else installed.

Two rules the design is firm about, both enforced here rather than left
to a caller:

- **Headers are `personal`, bodies are `sensitive`.** `search()`
  returns subjects, senders and a snippet; the body is fetched only by
  `fetch_body()`, one message at a time. If a search pulled every body
  back, the cheap operation would be the exposing one and nobody would
  notice.
- **Nothing here writes.** No flags set, no moves, no deletes, no
  sends. Reading mail is reversible and sending is not; the writing
  half of this domain is a later step with a human gate on it, and
  until then the connector cannot do it at all.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
from datetime import datetime, timezone

from simorgh.contracts.connector import Budget, ConnectorStatus, missing_requirements

from ..api import MailMessage

#: IMAP's own dialect of UTF-7 for non-ASCII folder names.
_B64_CHARS = re.compile(r"&([A-Za-z0-9+,]*)-")

DEFAULT_PORT = 993


def decode_folder(name: str) -> str:
    """`&AOk-` -> `é`. A person with a folder called "Rechnungen" is
    fine; one with "Écoles" saw mojibake without this."""
    import base64

    def _decode(match: re.Match) -> str:
        payload = match.group(1)
        if not payload:
            return "&"          # `&-` is a literal ampersand
        try:
            # IMAP's variant uses "," where base64 uses "/", and drops
            # the padding.
            raw = base64.b64decode(payload.replace(",", "/") + "===")
            return raw.decode("utf-16-be")
        except Exception:  # noqa: BLE001 -- an undecodable name is shown as-is
            return match.group(0)

    return _B64_CHARS.sub(_decode, name or "")


def decode_header(value: str) -> str:
    """RFC 2047 (`=?UTF-8?B?...?=`) into text. A subject line is the
    thing a person actually reads in a list of results, so leaving it
    encoded makes the whole result useless."""
    if not value:
        return ""
    parts = []
    for chunk, charset in email.header.decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", "replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def _address(value: str) -> str:
    name, addr = email.utils.parseaddr(decode_header(value or ""))
    return f"{name} <{addr}>".strip() if name else (addr or value or "")


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is not None and parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


class ImapConnector:
    """One mailbox, read-only."""

    packages: tuple[str, ...] = ()   # stdlib only, by design

    def __init__(self, *, name: str, host: str, username: str = "", password: str = "",
                 port: int = DEFAULT_PORT, ssl_enabled: bool = True, folders: tuple[str, ...] = (),
                 timeout_s: float = 20.0, client_factory=None, budget: Budget | None = None) -> None:
        self.name = name
        self.needs: tuple[str, ...] = (f"imap:{name}",)
        self.host = host
        self.port = port
        self._username = username
        self._password = password
        self._ssl = ssl_enabled
        self._folders = folders
        self._timeout = timeout_s
        self._factory = client_factory
        self._budget = budget or Budget(f"imap:{name}", limit=600, window_s=3600.0)
        self._client = None

    # -- lifecycle -----------------------------------------------------------

    async def probe(self) -> ConnectorStatus:
        missing = list(missing_requirements(
            ("host", "username", "password"),
            {"host": bool(self.host), "username": bool(self._username),
             "password": bool(self._password)}))
        if missing:
            return ConnectorStatus(
                False,
                f"{self.name}: set the IMAP host and username in [execution] pim_accounts, and "
                f"the password with `vault add imap:{self.name} password` (an app-specific "
                f"password, not the account password)",
                tuple(missing))
        try:
            client = await self._connect()
        except _MailError as exc:
            return ConnectorStatus(False, f"{self.name}: {exc}", ())
        except Exception as exc:  # noqa: BLE001 -- `probe()` may never raise
            return ConnectorStatus(False, f"{self.name}: could not sign in ({type(exc).__name__})", ())
        try:
            import asyncio

            folders = await asyncio.to_thread(lambda: client.list()[1] or [])
            return ConnectorStatus(True, f"{self.name}: signed in, {len(folders)} folder(s)")
        except Exception as exc:  # noqa: BLE001
            return ConnectorStatus(False, f"{self.name}: signed in but could not list folders ({exc!r})")

    async def close(self) -> None:
        import asyncio

        client, self._client = self._client, None
        if client is None:
            return

        def _shut():
            try:
                client.close()
            except Exception:  # noqa: BLE001 -- no selected mailbox is not an error
                pass
            try:
                client.logout()
            except Exception:  # noqa: BLE001
                pass

        await asyncio.to_thread(_shut)

    # -- reading -------------------------------------------------------------

    async def folders(self) -> list[str]:
        import asyncio

        client = await self._connect()
        self._budget.take()

        def _list():
            code, rows = client.list()
            if code != "OK":
                return []
            out = []
            for row in rows or []:
                text = row.decode("utf-8", "replace") if isinstance(row, bytes) else str(row)
                # `(\HasNoChildren) "/" "INBOX/Receipts"`
                match = re.search(r'"([^"]*)"\s*$', text) or re.search(r"(\S+)\s*$", text)
                if match:
                    out.append(decode_folder(match.group(1)))
            return out

        return await asyncio.to_thread(_list)

    async def search(self, query: str = "", *, folder: str = "INBOX", limit: int = 20,
                     since: datetime | None = None, unread_only: bool = False
                     ) -> list[MailMessage]:
        """Headers and a snippet. Never bodies -- see the module
        docstring."""
        import asyncio

        client = await self._connect()
        self._budget.take()

        def _search():
            code, _ = client.select(_quote(folder), readonly=True)
            if code != "OK":
                raise _MailError(f"no folder {folder!r}")
            criteria = _criteria(query, since=since, unread_only=unread_only)
            code, data = client.uid("SEARCH", None, *criteria)
            if code != "OK":
                raise _MailError("the server refused that search")
            uids = (data[0] or b"").split()
            # Newest first, and only as many as asked for: a mailbox
            # with 40,000 messages must not fetch 40,000 headers to show
            # twenty.
            uids = uids[::-1][:max(1, limit)]
            if not uids:
                return []
            code, rows = client.uid(
                "FETCH", b",".join(uids),
                "(FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE CONTENT-TYPE)])")
            if code != "OK":
                raise _MailError("the server refused to return those messages")
            return _messages(rows, folder=folder, account=self.name)

        return await asyncio.to_thread(_search)

    async def fetch_body(self, uid: str, *, folder: str = "INBOX", max_chars: int = 20_000
                         ) -> MailMessage | None:
        """One message, with its body. `sensitive` -- the caller decides
        what may see it."""
        import asyncio

        client = await self._connect()
        self._budget.take()

        def _fetch():
            code, _ = client.select(_quote(folder), readonly=True)
            if code != "OK":
                raise _MailError(f"no folder {folder!r}")
            code, rows = client.uid("FETCH", str(uid).encode(), "(FLAGS RFC822)")
            if code != "OK" or not rows or rows[0] is None:
                return None
            payload = rows[0][1] if isinstance(rows[0], tuple) else None
            if not payload:
                return None
            parsed = email.message_from_bytes(payload)
            body, attachments = _body_of(parsed, max_chars=max_chars)
            return MailMessage(
                uid=str(uid), folder=folder, account=self.name,
                subject=decode_header(parsed.get("Subject", "")),
                sender=_address(parsed.get("From", "")),
                to=tuple(_address(a) for a in (parsed.get_all("To") or [])),
                date=_parse_date(parsed.get("Date", "")),
                body=body, snippet=body[:200], has_attachments=attachments,
                flags=tuple(_flags(rows[0])),
            )

        return await asyncio.to_thread(_fetch)

    # -- plumbing ------------------------------------------------------------

    async def _connect(self):
        import asyncio

        if self._client is not None:
            return self._client

        def _open():
            try:
                if self._factory is not None:
                    client = self._factory()
                elif self._ssl:
                    client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self._timeout)
                else:
                    client = imaplib.IMAP4(self.host, self.port, timeout=self._timeout)
            except OSError as exc:
                raise _MailError(f"could not reach {self.host}:{self.port} ({exc.strerror or exc})") from exc
            try:
                client.login(self._username, self._password)
            except Exception:  # noqa: BLE001 -- see below; the type varies by client
                # Deliberately broad, and deliberately discarding the
                # original. `imaplib` puts the whole LOGIN command in
                # `str(exc)`, and the LOGIN command contains the
                # password -- so no part of it may reach a ToolResult,
                # a log, or a `raise ... from exc` chain that a
                # traceback would print. Catching only
                # `imaplib.IMAP4.error` also let a stray `OSError` (a
                # connection dropped mid-login) escape `probe()`, which
                # the connector contract forbids outright.
                raise _MailError(
                    "the server refused these credentials. Most providers need an "
                    "app-specific password here, not the account password."
                ) from None
            return client

        self._client = await asyncio.to_thread(_open)
        return self._client


class _MailError(RuntimeError):
    """A mail problem phrased for a person, and guaranteed to carry no
    credential -- `imaplib` puts the whole LOGIN command in its own
    exception strings."""


def _quote(folder: str) -> str:
    return f'"{folder}"' if " " in folder else folder


def _criteria(query: str, *, since: datetime | None, unread_only: bool) -> list[str]:
    out: list[str] = []
    if unread_only:
        out.append("UNSEEN")
    if since is not None:
        out.extend(["SINCE", since.strftime("%d-%b-%Y")])
    query = (query or "").strip()
    if query:
        # TEXT searches headers and body; a person typing a name means
        # "find it wherever it is", not "in the subject only".
        out.extend(["TEXT", f'"{query}"'])
    return out or ["ALL"]


def _flags(row) -> list[str]:
    text = ""
    if isinstance(row, tuple) and row and isinstance(row[0], bytes):
        text = row[0].decode("utf-8", "replace")
    elif isinstance(row, bytes):
        text = row.decode("utf-8", "replace")
    match = re.search(r"FLAGS \(([^)]*)\)", text)
    return match.group(1).split() if match else []


def _messages(rows, *, folder: str, account: str) -> list[MailMessage]:
    out: list[MailMessage] = []
    for row in rows or []:
        if not isinstance(row, tuple) or len(row) < 2 or not row[1]:
            continue
        head = row[0].decode("utf-8", "replace") if isinstance(row[0], bytes) else str(row[0])
        uid_match = re.search(r"UID (\d+)", head)
        size_match = re.search(r"RFC822\.SIZE (\d+)", head)
        parsed = email.message_from_bytes(row[1])
        content_type = (parsed.get("Content-Type", "") or "").lower()
        out.append(MailMessage(
            uid=uid_match.group(1) if uid_match else "",
            folder=folder, account=account,
            subject=decode_header(parsed.get("Subject", "")),
            sender=_address(parsed.get("From", "")),
            to=tuple(_address(a) for a in (parsed.get_all("To") or [])),
            date=_parse_date(parsed.get("Date", "")),
            flags=tuple(_flags(row)),
            size=int(size_match.group(1)) if size_match else 0,
            has_attachments="multipart/mixed" in content_type,
        ))
    return out


def _body_of(message, *, max_chars: int) -> tuple[str, bool]:
    """The text of a message, and whether it has attachments.

    Prefers `text/plain`. An HTML-only message is stripped rather than
    dropped: `htmltext` is the same converter `web_fetch` uses, so a
    newsletter reads the same wherever it came from.
    """
    attachments = False
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk():
        disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            attachments = True
            continue
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            continue
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, "replace")
        (plain if content_type == "text/plain" else html).append(text)

    body = "\n".join(plain).strip()
    if not body and html:
        from ...htmltext import html_to_text

        text, _truncated = html_to_text("\n".join(html))
        body = text.strip()
    return body[:max_chars], attachments


__all__ = ["DEFAULT_PORT", "ImapConnector", "decode_folder", "decode_header"]
