"""The pim tools: `cal_list`, `mail_search`, `mail_read`, `remind`.

Step 1 of the domain's build order, plus `remind` from step 2. Reading
only -- no `mail_send`, no `cal_create`, no flags, no moves. That is not
an oversight: sending is irreversible and gets a human gate
(`domains/02-calendar-mail-tasks.md` section 5), and a connector that
cannot write at all is a stronger guarantee than a policy that says it
should not.

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

import uuid
from datetime import datetime, timezone

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
        return ToolResult(
            ok=False,
            error=(f"refused: no {kind} account is configured. Add one to simorgh.toml:\n{example}\n"
                   f"then store the password with `vault add {kind}:<name> password` "
                   f"(an app-specific password, not the account password)."))


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
            return ToolResult(ok=False, error=f"refused: {exc}")

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
        },
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        connectors = self._of_kind("imap")
        if not connectors:
            return self._nothing_configured("imap")
        wanted = str(args.get("account") or "").strip()
        if wanted and wanted not in connectors:
            return ToolResult(ok=False, error=(f"refused: no mail account {wanted!r}; "
                                                f"configured: {', '.join(sorted(connectors))}"))
        chosen = {wanted: connectors[wanted]} if wanted else connectors
        limit = max(1, min(int(args.get("limit") or 20),
                           int(getattr(self._config, "pim_max_results", 50))))
        since = None
        if args.get("since"):
            try:
                since, _ = parse_range(str(args["since"]), now=self._now())
            except Ambiguous as exc:
                return ToolResult(ok=False, error=f"refused: {exc}")

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
        if problems:
            body += "\n\ncould not read:\n" + "\n".join(f"- {p}" for p in problems)
        rows = [{"uid": m.uid, "account": m.account, "folder": m.folder, "subject": m.subject,
                 "from": m.sender, "date": m.date.isoformat() if m.date else "",
                 "unread": m.unread, "attachments": m.has_attachments} for m in messages]
        # Subjects and senders are `personal` and go in rows so
        # `query_data` can count them. A body never does.
        return ToolResult(ok=not (problems and not messages), output=body,
                          error=("; ".join(problems) if problems and not messages else None),
                          metadata={"messages": len(messages), "rows": rows,
                                    "privacy": "personal"})


class MailReadTool(_PimTool):
    name = "mail_read"
    description = (
        "Open one message and read its body. Takes the [account:folder:uid] reference "
        "mail_search printed."
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
        reference = str(args.get("message") or "").strip().strip("[]")
        if not reference:
            return ToolResult(ok=False, error="refused: no message given")
        parts = reference.split(":")
        if len(parts) == 3:
            account, folder, uid = parts
        elif len(parts) == 2:
            account, folder, uid = "", parts[0], parts[1]
        else:
            account, folder, uid = "", "INBOX", parts[0]
        account = account or next(iter(sorted(connectors)))
        if account not in connectors:
            return ToolResult(ok=False, error=(f"refused: no mail account {account!r}; "
                                                f"configured: {', '.join(sorted(connectors))}"))

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
                        f"{reference} themselves, or add 'sensitive' to that setting."),
                metadata={"withheld": True, "privacy": "sensitive"})

        try:
            message = await connectors[account].fetch_body(
                uid, folder=folder,
                max_chars=int(getattr(self._config, "pim_body_max_chars", 20_000)))
        except BudgetExhausted as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")
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
                       "every": {"type": "boolean"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        text = " ".join(str(args.get("text") or "").split())
        if not text:
            return ToolResult(ok=False, error="refused: a reminder with nothing to say")
        when_text = str(args.get("when") or "").strip()
        now = self._now()
        try:
            fires_at = parse_when(when_text, now=now)
        except Ambiguous as exc:
            # Never a guess. A reminder that fires on the wrong day is
            # worse than one that was never set.
            return ToolResult(ok=False, error=f"refused: {exc}")

        delay = (fires_at - now).total_seconds()
        if delay <= 0:
            return ToolResult(ok=False,
                              error=f"refused: {fires_at:%a %d %b %H:%M} is in the past")
        maximum = float(getattr(self._config, "pim_max_reminder_days", 365)) * 86400
        if delay > maximum:
            return ToolResult(ok=False,
                              error=(f"refused: {fires_at:%d %b %Y} is more than "
                                     f"{int(maximum // 86400)} days away"))
        if ctx.bus is None:
            return ToolResult(ok=False,
                              error="refused: reminders need the bus, which this session has not got")

        schedule_id = uuid.uuid4().hex[:12]
        recurring = bool(args.get("every"))
        payload = {
            "schedule_id": schedule_id, "label": text,
            "at": None if recurring else (ctx.clock.now() if ctx.clock else now.timestamp()) + delay,
            "every_seconds": delay if recurring else None,
        }
        await ctx.bus.publish(Message.new(topics.SYSTEM_SCHEDULE_ADD, source="execution",
                                          payload=payload))
        when = (f"every {_human(delay)}" if recurring
                else f"{fires_at:%a %d %b at %H:%M} (in {_human(delay)})")
        return ToolResult(ok=True, output=f"reminder set for {when}: {text}  ({schedule_id})",
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
            MailReadTool(config, **kwargs), RemindTool(config, **kwargs)]


__all__ = ["CalListTool", "MailReadTool", "MailSearchTool", "RemindTool", "pim_tools"]
