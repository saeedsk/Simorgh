"""Domain 2: calendar, mail and tasks
(`docs/plans/domains/02-calendar-mail-tasks.md`).

Sim reads the creator's calendar and mail, and turns "tomorrow 3pm with
the plumber" into a reminder that actually fires.

Two decisions shaped this package, both away from the design's first
draft:

**No pip dependency for either half.** The design named `caldav` and
`imapclient`. `imaplib` and `email` are stdlib, and CalDAV is HTTP plus
XML plus iCalendar -- all three of which are also stdlib. So both
connectors are written directly, and mail and calendar work on a fresh
machine with nothing but an account. "Local first, cloud as a named
tier" is about capability, and a capability that needs a pip install
before it can be tried is one tier further away than it needs to be.
The `caldav` package remains the better client for the exotic corners
(free/busy scheduling, ACLs); when a corner needs it, it goes behind
the same `Connector` interface.

**The connectors live under `execution/`, not `contracts/`.** The
handover put them in `contracts/connectors/`, and the boundary rules do
allow it. But `contracts` is protocol definitions -- things every
subsystem may import precisely because they carry no behaviour -- and
an IMAP client with a socket in it is not that. The `Connector`
protocol stays in contracts; the things that implement it live next to
their only caller, exactly as `execution/knowledge/` does.
"""

from .api import Account, Calendar, Event, MailMessage, Task

__all__ = ["Account", "Calendar", "Event", "MailMessage", "Task"]
