"""The pim tools: `cal_list`, `mail_search`, `mail_read`, `mail_unsubscribe`, `remind`.

Step 1 of the domain's build order, plus `remind` from step 2. Reading
only -- no `mail_send`, no `cal_create`, no flags, no moves. That is not
an oversight: sending is irreversible and gets a human gate
(`domains/02-calendar-mail-tasks.md` section 5), and a connector that
cannot write at all is a stronger guarantee than a policy that says it
should not.

`mail_unsubscribe` (2026-10-27) is the one exception that reaches out:
it never writes to the mailbox, but it POSTs the sender's own RFC 8058
one-click link, which the creator asked for by voice ("I need you to be
able to do so"). It is irreversible, so Guardian sees it as such.

`remind` is the one that changes something, and it changes something
entirely local: it compiles to a Kernel schedule. The Kernel has had a
complete scheduler since the beginning, and `schedule` (the CLI
command) was the first door into it. This is the second, and the one a
person actually reaches for -- "remind me to take the bins out at 7"
rather than "schedule 16h30m ...".

Privacy, from platform section 10: **headers are `personal`, bodies are
`sensitive`.** `mail_search` returns subjects and senders; `mail_read`
is the only thing that fetches a body, and it refuses when the
configured session may not see that class.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.connector import BudgetExhausted
from simorgh.contracts.protocols import ToolContext, ToolResult

from .accounts import build_all, parse_accounts
from .nlp import Ambiguous, parse_range, parse_when

_PRIVACY_ORDER = {"public": 0, "personal": 1, "sensitive": 2, "secret": 3}


class _PimTool:
    """Shared: build the connectors once, and answer usefully when none
    is configured -- which is the state this ships in."""

    def __init__(self, config, *, connectors=None, secrets=None, env=None, clock=None) -> None:
        self._config = config
        self._given = connectors
        self._secrets = secrets
        self._env = env
        self._clock = clock
        self._built = None

    def _connectors(self) -> dict:
        if self._given is not None:
            return self._given
        if self._built is None:
            self._built = build_all(
                getattr(self._config, "pim_accounts", ()),
                secrets=self._secrets, env=self._env,
                timeout_s=float(getattr(self._config, "pim_timeout_s", 20.0)))
        return self._built

    def _of_kind(self, kind: str) -> dict:
        wanted = {account.name for account in parse_accounts(
            getattr(self._config, "pim_accounts", ())) if account.kind == kind}
        connectors = self._connectors()
        if self._given is not None and not wanted:
            # Injected connectors (tests, and a caller wiring its own)
            # are taken at face value: asking config which of them is a
            # mailbox would just be asking the wrong question.
            return {name: c for name, c in connectors.items() if _looks_like(c, kind)}
        return {name: c for name, c in connectors.items() if name in wanted}

    def _now(self) -> datetime:
        if self._clock is not None:
            value = self._clock() if callable(self._clock) else self._clock.now()
            return datetime.fromtimestamp(value)
        return datetime.now()

    def _may_see(self) -> tuple[str, ...]:
        return tuple(getattr(self._config, "pim_cloud_llm_may_see", ("public", "personal")))

    @staticmethod
    def _nothing_configured(kind: str) -> ToolResult:
        example = ('[[execution.pim_accounts]]\nname = "fastmail"\nkind = "imap"\n'
                   'url = "imap.fastmail.com"\nusername = "you@example.com"'
                   if kind == "imap" else
                   '[[execution.pim_accounts]]\nname = "home"\nkind = "caldav"\n'
                   'url = "https://caldav.fastmail.com/dav/calendars/user/you/"\n'
                   'username = "you@example.com"')
        return ToolResult.unconfigured(f"refused: no {kind} account is configured. Add one to simorgh.toml:\n{example}\n"
                   f"then store the password with `vault add {kind}:<name> password` "
                   f"(an app-specific password, not the account password).")


def _looks_like(connector, kind: str) -> bool:
    if kind == "imap":
        return hasattr(connector, "search") and hasattr(connector, "fetch_body")
    return hasattr(connector, "events")


class CalListTool(_PimTool):
    name = "cal_list"
    description = (
        "What is on the creator's calendar. Takes a range like \"today\", \"tomorrow\", "
        "\"this week\" or an ISO date."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object",
        "properties": {"range": {"type": "string"}, "calendar": {"type": "string"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        connectors = self._of_kind("caldav")
        if not connectors:
            return self._nothing_configured("caldav")
        try:
            start, end = parse_range(str(args.get("range") or "today"), now=self._now())
        except Ambiguous as exc:
            return ToolResult.refused(f"refused: {exc}")

        wanted = str(args.get("calendar") or "").strip().lower()
        events, problems = [], []
        for name, connector in connectors.items():
            try:
                found = await connector.events(start, end)
            except BudgetExhausted as exc:
                problems.append(f"{name}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 -- one unreachable account is not a failed call
                status = await _safe_probe(connector)
                problems.append(f"{name}: {status or _clean(exc)}")
                continue
            events.extend(e for e in found
                          if not wanted or wanted in (e.calendar or name).lower())

        events.sort(key=lambda event: (event.start.replace(tzinfo=None), event.summary))
        window = f"{start:%a %d %b} to {end:%a %d %b}"
        if not events:
            body = f"nothing on the calendar for {window}"
        else:
            body = f"{len(events)} event(s), {window}:\n" + "\n".join(
                "  " + event.render() for event in events)
        if problems:
            body += "\n\ncould not read:\n" + "\n".join(f"- {p}" for p in problems)
        rows = [{"uid": e.uid, "summary": e.summary, "start": e.start.isoformat(),
                 "end": e.end.isoformat() if e.end else "", "location": e.location,
                 "calendar": e.calendar, "all_day": e.all_day} for e in events]
        return ToolResult(ok=not (problems and not events), output=body,
                          error=("; ".join(problems) if problems and not events else None),
                          metadata={"events": len(events), "rows": rows,
                                    "from": start.isoformat(), "to": end.isoformat()})


_BACK = {"day": 1, "week": 7, "month": 30, "year": 365}
#: Most messages one `group_by=sender` count reads (From headers only).
MAX_COUNTED = 5000


def since_of(text: str, *, now: datetime) -> datetime:
    """Where a `since=` reaches back to. "30 days", "past month", "last 2
    weeks" look BACK from now; anything else ("this week", "yesterday", an
    ISO date) is the start of `parse_range`'s range. `parse_range` alone
    reads "30 days" forward, as a calendar does -- for mail that was
    "since midnight today"."""
    match = re.fullmatch(r"\s*(?:(?:the\s+)?(?:past|last)\s+)?(\d+)?\s*(day|week|month|year)s?\s*(?:ago)?\s*",
                         text.lower())
    if match:
        return now - timedelta(days=int(match.group(1) or 1) * _BACK[match.group(2)])
    start, _ = parse_range(text, now=now)
    return start


class MailSearchTool(_PimTool):
    name = "mail_search"
    description = (
        "Search the creator's mailbox and get back subjects, senders and dates. "
        "Bodies are not included -- use mail_read for one message."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"}, "folder": {"type": "string"},
            "account": {"type": "string"}, "limit": {"type": "integer"},
            "since": {"type": "string"}, "unread_only": {"type": "boolean"},
            "group_by": {"type": "string", "enum": ["sender"]}, "top": {"type": "integer"},
        },
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        connectors = self._of_kind("imap")
        if not connectors:
            return self._nothing_configured("imap")
        wanted = str(args.get("account") or "").strip()
        if wanted and wanted not in connectors:
            return ToolResult.refused(f"refused: no mail account {wanted!r}; "
                                                f"configured: {', '.join(sorted(connectors))}")
        chosen = {wanted: connectors[wanted]} if wanted else connectors
        limit = max(1, min(int(args.get("limit") or 20),
                           int(getattr(self._config, "pim_max_results", 50))))
        since = None
        if args.get("since"):
            try:
                since = since_of(str(args["since"]), now=self._now())
            except Ambiguous as exc:
                return ToolResult.refused(f"refused: {exc}")

        if str(args.get("group_by") or "").strip().lower() == "sender":
            return await self._by_sender(chosen, args, since)

        messages, problems = [], []
        for name, connector in chosen.items():
            try:
                messages.extend(await connector.search(
                    str(args.get("query") or ""), folder=str(args.get("folder") or "INBOX"),
                    limit=limit, since=since, unread_only=bool(args.get("unread_only"))))
            except BudgetExhausted as exc:
                problems.append(f"{name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                status = await _safe_probe(connector)
                problems.append(f"{name}: {status or _clean(exc)}")

        messages.sort(key=lambda m: (m.date or datetime.min.replace(tzinfo=timezone.utc)),
                      reverse=True)
        messages = messages[:limit]
        if not messages:
            body = "no messages matched"
        else:
            body = (f"{len(messages)} message(s) (`*` is unread). Use MAIL_READ with a uid to "
                    f"open one:\n" + "\n".join(
                        f"  [{m.account}:{m.folder}:{m.uid}]{m.render()}" for m in messages))
        if len(messages) == limit:
            # Newest first and cut at `limit`: a count over these is a count
            # over the newest `limit`, not over the range. Sim reported the
            # "top five promo senders of the month" from the newest twenty,
            # twice (live 2026-10-28).
            cap = int(getattr(self._config, "pim_max_results", 50))
            body += (f"\n\nStopped at the limit of {limit}: older matches were not fetched. Before "
                     f"counting over a range, search again with a larger limit (up to {cap}) or a "
                     f"narrower since= and say how many you saw."
                     if limit < cap else
                     f"\n\nStopped at the cap of {cap}: older matches were not fetched. Search "
                     f"narrower ranges with since= and say how many you saw.")
        if problems:
            body += "\n\ncould not read:\n" + "\n".join(f"- {p}" for p in problems)
        # `ref` is what mail_read takes, ready-made: a program that rebuilt it
        # from fields a later row did not carry sent `[None:None:None]` 71
        # times (live 2026-10-30).
        rows = [{"ref": f"[{m.account}:{m.folder}:{m.uid}]", "uid": m.uid, "account": m.account,
                 "folder": m.folder, "subject": m.subject,
                 "from": m.sender, "date": m.date.isoformat() if m.date else "",
                 "unread": m.unread, "attachments": m.has_attachments} for m in messages]
        # Subjects and senders are `personal` and go in rows so
        # `query_data` can count them. A body never does.
        return ToolResult(ok=not (problems and not messages), output=body,
                          error=("; ".join(problems) if problems and not messages else None),
                          metadata={"messages": len(messages), "rows": rows,
                                    "privacy": "personal"})


    async def _by_sender(self, chosen, args, since):
        """`group_by=sender`: messages per sender over the whole range, every
        account, every page -- the answer to "who sends me the most"."""
        cap = MAX_COUNTED
        top = max(1, min(int(args.get("top") or 10), 100))
        totals: dict[str, int] = {}
        matched = counted = 0
        problems = []
        for name, connector in chosen.items():
            try:
                counts, m, c = await connector.sender_counts(
                    str(args.get("query") or ""), folder=str(args.get("folder") or "INBOX"), since=since,
                    unread_only=bool(args.get("unread_only")), max_messages=cap)
            except BudgetExhausted as exc:
                problems.append(f"{name}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                status = await _safe_probe(connector)
                problems.append(f"{name}: {status or _clean(exc)}")
                continue
            matched, counted = matched + m, counted + c
            for sender, n in counts.items():
                totals[sender] = totals.get(sender, 0) + n
        span = f"since {since:%Y-%m-%d}" if since else "in the whole folder"
        if not counted:
            body = f"no messages matched {span}"
        else:
            ranked = _sender_table(totals, top)
            body = (f"{counted} message(s) {span} from {len(totals)} sender(s), every one counted"
                    + (f" (of {matched} matched; the newest {counted} -- count the rest with a "
                       f"narrower since=)" if counted < matched else "")
                    + f". Top {len(ranked)} by messages:\n"
                    + "\n".join(f"  {i}. {sender} -- {n}" for i, (sender, n) in enumerate(ranked, 1)))
        if problems:
            body += "\n\ncould not read:\n" + "\n".join(f"- {p}" for p in problems)
        rows = [{"sender": s, "messages": n} for s, n in _sender_table(totals, len(totals))]
        return ToolResult(ok=not (problems and not counted), output=body,
                          error=("; ".join(problems) if problems and not counted else None),
                          metadata={"messages": counted, "matched": matched, "senders": len(totals), "rows": rows,
                                    "privacy": "personal"})


def _sender_table(counts: dict, top: int) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:top]


#: Most messages one mail_read opens. A program over a page of mail
#: (`run_analysis`, `sim.call`) has `workbench_max_calls` calls a run: one
#: message a call read 50 of 200 and called the other 150 unreadable
#: (live 2026-10-30, task cef68b40).
MAIL_READ_BATCH = 20
#: Least of each body a batch shows: the batch shares one body's budget.
_BATCH_MIN_CHARS = 1000


def _references(text) -> list[str]:
    """The references in mail_read's one line: space- or comma-separated,
    brackets optional."""
    return [r for r in (p.strip().strip("[]") for p in re.split(r"[\s,]+", str(text or ""))) if r]


class MailReadTool(_PimTool):
    name = "mail_read"
    description = (
        "Open a message and read its body. Takes the [account:folder:uid] reference "
        f"mail_search printed (a row's `ref`), or up to {MAIL_READ_BATCH} of them on one line, separated "
        "by spaces; each message then starts with a line `=== [account:folder:uid] ===`."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object", "required": ["message"],
        "properties": {"message": {"type": "string"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        connectors = self._of_kind("imap")
        if not connectors:
            return self._nothing_configured("imap")
        references = _references(args.get("message"))
        if not references:
            return ToolResult.refused("refused: no message given")
        if len(references) > MAIL_READ_BATCH:
            return ToolResult.refused(f"refused: {len(references)} references; mail_read opens at most "
                                      f"{MAIL_READ_BATCH} a call -- split them")

        # A body is `sensitive`. The gate is here rather than in the
        # caller because the caller is a model, and by the time it could
        # decide the text is already in its context.
        allowed = self._may_see()
        if _PRIVACY_ORDER["sensitive"] > max(_PRIVACY_ORDER.get(c, 0) for c in allowed):
            return ToolResult(
                ok=True,
                output=(f"Message bodies are classed 'sensitive' and this session may not show "
                        f"them (`[execution] pim_cloud_llm_may_see` = {list(allowed)}). "
                        f"mail_search gives you the subject and sender; the person can read "
                        f"{' '.join(references)} themselves, or add 'sensitive' to that setting."),
                metadata={"withheld": True, "privacy": "sensitive"})

        max_chars = int(getattr(self._config, "pim_body_max_chars", 20_000))
        if len(references) == 1:
            return await self._read_one(references[0], connectors, max_chars)
        share = max(_BATCH_MIN_CHARS, max_chars // len(references))
        blocks, read = [], 0
        for reference in references:
            result = await self._read_one(reference, connectors, share)
            meta = result.metadata or {}
            label = (f"[{meta['account']}:{meta['folder']}:{meta['uid']}]" if result.ok else f"[{reference}]")
            read += bool(result.ok)
            blocks.append(f"=== {label} ===\n" + (result.output if result.ok else f"could not read: {result.error}"))
        return ToolResult(ok=read > 0, output="\n\n".join(blocks),
                          error=None if read else "no message could be read",
                          metadata={"privacy": "sensitive", "withheld": False, "read": read,
                                    "failed": len(references) - read})

    async def _read_one(self, reference: str, connectors: dict, max_chars: int) -> ToolResult:
        account, folder, uid = _reference(reference, connectors)
        if not uid:
            # `[None:None:None]`: a program built it from row fields that
            # were not there (live 2026-10-30).
            return ToolResult.refused(f"refused: {reference!r} names no message uid; pass a mail_search "
                                      f"row's `ref` as it is, e.g. [{account}:{folder}:301592]")
        if account not in connectors:
            return ToolResult.refused(f"refused: no mail account {account!r}; "
                                                f"configured: {', '.join(sorted(connectors))}")
        try:
            message = await connectors[account].fetch_body(uid, folder=folder, max_chars=max_chars)
        except BudgetExhausted as exc:
            return ToolResult.from_exception(exc, f"refused: {exc}", default="refused")
        except Exception as exc:  # noqa: BLE001
            status = await _safe_probe(connectors[account])
            return ToolResult(ok=False, error=f"{account}: {status or _clean(exc)}")

        if message is None:
            return ToolResult(ok=False, error=f"no message {uid!r} in {folder!r} on {account!r}")
        when = message.date.strftime("%a %d %b %Y %H:%M") if message.date else "(no date)"
        header = (f"From: {message.sender}\nTo: {', '.join(message.to)}\nDate: {when}\n"
                  f"Subject: {message.subject}")
        if message.has_attachments:
            header += "\nAttachments: yes (open them with read_file if they are saved to disk)"
        return ToolResult(ok=True, output=f"{header}\n\n{message.body}",
                          metadata={"uid": message.uid, "account": account, "folder": folder,
                                    "privacy": "sensitive", "withheld": False,
                                    "chars": len(message.body)})


_LINK = re.compile(r"<\s*([^<>\s]+)\s*>")


def unsubscribe_links(header: str) -> tuple[list[str], list[str]]:
    """`List-Unsubscribe`'s https and mailto links, in the sender's order
    (RFC 2369: angle brackets, comma separated). Plain http is dropped:
    RFC 8058 one-click is https only, and a token in clear text is not
    something Sim sends."""
    https, mailto = [], []
    for link in _LINK.findall(header or ""):
        lowered = link.lower()
        if lowered.startswith("https://"):
            https.append(link)
        elif lowered.startswith("mailto:"):
            mailto.append(link[7:].split("?", 1)[0])
    return https, mailto


def _public_https(url: str) -> str:
    """Why `url` may not be posted to, or "" when it may: https only, and
    never a host that resolves to this house's own network."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return "not an https link"
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return f"could not resolve {parts.hostname} ({exc.strerror or exc})"
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            return f"{parts.hostname} is not a public address"
    return ""


def one_click_post(url: str, *, timeout_s: float = 15.0) -> int:
    """RFC 8058 section 3.1: POST `List-Unsubscribe=One-Click` to the
    https link. Returns the HTTP status; raises on a refusal or a
    network failure."""
    import urllib.request

    why = _public_https(url)
    if why:
        raise ValueError(why)
    request = urllib.request.Request(
        url, data=b"List-Unsubscribe=One-Click", method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Simorgh/1 (one-click)"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 -- https only, checked above
        return int(response.status)


class MailUnsubscribeTool(_PimTool):
    name = "mail_unsubscribe"
    description = (
        "Unsubscribe the creator from a sender's mailing list, using the unsubscribe offer in the "
        "message's own headers (one-click, RFC 8058) -- no browser, no clicking. Takes one or more "
        "[account:folder:uid] references from mail_search, one per sender. Says, per sender, whether it "
        "is done, or that the sender only offers a page (open it with browse_page) or an email address."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {
        "type": "object", "required": ["messages"],
        "properties": {"messages": {"type": "array", "items": {"type": "string"}}},
    }

    def __init__(self, config, *, post=None, **kwargs) -> None:
        super().__init__(config, **kwargs)
        self._post = post

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import asyncio

        connectors = self._of_kind("imap")
        if not connectors:
            return self._nothing_configured("imap")
        given = args.get("messages") or []
        if isinstance(given, str):
            given = re.split(r"[\s,]+", given)
        references = [str(r).strip().strip("[]") for r in given if str(r).strip().strip("[]")]
        if not references:
            return ToolResult.refused("refused: no message given -- pass the [account:folder:uid] "
                                      "references mail_search printed, one per sender")
        post = self._post or one_click_post
        lines, rows, seen = [], [], set()
        for reference in references[:20]:
            account, folder, uid = _reference(reference, connectors)
            if account not in connectors:
                lines.append(f"- {reference}: no mail account {account!r}")
                continue
            try:
                found = await connectors[account].unsubscribe_headers(uid, folder=folder)
            except BudgetExhausted as exc:
                lines.append(f"- {reference}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                lines.append(f"- {reference}: {_clean(exc)}")
                continue
            if found is None:
                lines.append(f"- {reference}: no such message")
                continue
            sender = found["sender"] or reference
            if sender.lower() in seen:
                continue
            seen.add(sender.lower())
            https, mailto = unsubscribe_links(found["list_unsubscribe"])
            one_click = "one-click" in found["list_unsubscribe_post"].lower().replace(" ", "")
            row = {"sender": sender, "message": reference, "state": "", "link": ""}
            if https and one_click:
                try:
                    status = await asyncio.to_thread(post, https[0])
                except Exception as exc:  # noqa: BLE001 -- a refusal or the network; said per sender
                    row.update(state="failed", link=https[0])
                    lines.append(f"- {sender}: the one-click unsubscribe failed ({_clean(exc)}); "
                                 f"the page is {https[0]}")
                else:
                    if 200 <= status < 300:
                        row["state"] = "done"
                        lines.append(f"- {sender}: unsubscribed (one-click, HTTP {status})")
                    else:
                        row.update(state="failed", link=https[0])
                        lines.append(f"- {sender}: the sender answered HTTP {status}, so it is not done; "
                                     f"the page is {https[0]}")
            elif https:
                row.update(state="page", link=https[0])
                lines.append(f"- {sender}: no one-click offer; the unsubscribe page is {https[0]} "
                             f"-- browse_page can open it and press the button")
            elif mailto:
                row.update(state="email", link=mailto[0])
                lines.append(f"- {sender}: only unsubscribes by email to {mailto[0]}, and I cannot send mail")
            else:
                row["state"] = "none"
                lines.append(f"- {sender}: the message carries no unsubscribe offer; the link at the "
                             f"bottom of the email (mail_read) is the only way")
            rows.append(row)
        done = sum(1 for r in rows if r["state"] == "done")
        body = f"{done} of {len(rows)} sender(s) unsubscribed:\n" + "\n".join(lines)
        effects = [f"mail:unsubscribe:{r['sender']}" for r in rows if r["state"] == "done"]
        return ToolResult(ok=bool(rows), output=body, error=None if rows else "nothing could be unsubscribed",
                          side_effects=tuple(effects), metadata={"rows": rows, "done": done, "privacy": "personal"})


#: A reference part a program filled from a field its row did not have.
_MISSING = frozenset({"", "none", "null", "undefined"})


def _reference(reference: str, connectors: dict) -> tuple[str, str, str]:
    """`account:folder:uid`, `folder:uid` or `uid`, as mail_read reads it.
    A missing part (`[None:None:301592]`) takes its default: the first
    account, the inbox; a missing uid stays empty for the caller to refuse."""
    parts = [p.strip() for p in reference.split(":")]
    parts = ["" if p.lower() in _MISSING else p for p in parts]
    if len(parts) == 3:
        account, folder, uid = parts
    elif len(parts) == 2:
        account, folder, uid = "", parts[0], parts[1]
    else:
        account, folder, uid = "", "INBOX", parts[0]
    return account or next(iter(sorted(connectors))), folder or "INBOX", uid


class RemindTool(_PimTool):
    name = "remind"
    description = (
        "Set a reminder. Takes a time (\"20m\", \"tomorrow 9am\", \"friday at 15:00\") and "
        "what to say. It fires even if nobody is at the terminal."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["when", "text"],
        "properties": {"when": {"type": "string"}, "text": {"type": "string"},
                       "every": {"type": "boolean"},
                       # Whose reminder it is. Initiative routes the
                       # `reminder` class "to its person wherever they
                       # are" (stage 6 item 6) and it has never been
                       # able to: it reads `person` off the fired
                       # event, the event never carried one, and
                       # neither did the schedule or this tool. So
                       # every reminder in the house was a household
                       # announcement. Empty still means the household.
                       "person": {"type": "string"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        text = " ".join(str(args.get("text") or "").split())
        if not text:
            return ToolResult.refused("refused: a reminder with nothing to say")
        when_text = str(args.get("when") or "").strip()
        now = self._now()
        try:
            fires_at = parse_when(when_text, now=now)
        except Ambiguous as exc:
            # Never a guess. A reminder that fires on the wrong day is
            # worse than one that was never set.
            return ToolResult.refused(f"refused: {exc}")

        delay = (fires_at - now).total_seconds()
        if delay <= 0:
            return ToolResult.refused(f"refused: {fires_at:%a %d %b %H:%M} is in the past")
        maximum = float(getattr(self._config, "pim_max_reminder_days", 365)) * 86400
        if delay > maximum:
            return ToolResult.refused(f"refused: {fires_at:%d %b %Y} is more than "
                                     f"{int(maximum // 86400)} days away")
        if ctx.bus is None:
            return ToolResult.unconfigured("refused: reminders need the bus, which this session has not got")

        schedule_id = uuid.uuid4().hex[:12]
        recurring = bool(args.get("every"))
        payload = {
            "schedule_id": schedule_id, "label": text,
            "at": None if recurring else (ctx.clock.now() if ctx.clock else now.timestamp()) + delay,
            "every_seconds": delay if recurring else None,
        }
        person = " ".join(str(args.get("person") or "").split())
        if person:
            payload["person"] = person
        await ctx.bus.publish(Message.new(topics.SYSTEM_SCHEDULE_ADD, source="execution",
                                          payload=payload))
        when = (f"every {_human(delay)}" if recurring
                else f"{fires_at:%a %d %b at %H:%M} (in {_human(delay)})")
        whose = f" for {person}" if person else ""
        return ToolResult(ok=True, output=f"reminder{whose} set for {when}: {text}  ({schedule_id})",
                          side_effects=(f"schedule {schedule_id} added",),
                          metadata={"schedule_id": schedule_id, "at": payload["at"],
                                    "every_seconds": payload["every_seconds"],
                                    "fires_at": fires_at.isoformat()})


def _human(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds / 3600:.0f}h"
    return f"{seconds / 86400:.0f}d"


def _clean(exc: Exception) -> str:
    """An exception rendered for a person -- and never with a credential
    in it. `imaplib` puts the whole LOGIN command in its own error
    strings, password included, so nothing here uses `repr(exc)`."""
    text = str(exc) or exc.__class__.__name__
    return text.split("\n")[0][:200]


async def _safe_probe(connector) -> str:
    """A failed call usually means a configuration problem the probe can
    explain far better than the exception can."""
    try:
        status = await connector.probe()
    except Exception:  # noqa: BLE001
        return ""
    return "" if status.ok else status.detail


def pim_tools(config, **kwargs) -> list:
    return [CalListTool(config, **kwargs), MailSearchTool(config, **kwargs),
            MailReadTool(config, **kwargs), MailUnsubscribeTool(config, **kwargs), RemindTool(config, **kwargs)]


__all__ = ["CalListTool", "MailReadTool", "MailSearchTool", "MailUnsubscribeTool", "RemindTool", "one_click_post",
           "pim_tools", "unsubscribe_links"]
