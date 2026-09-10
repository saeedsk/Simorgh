# Domain 2: Calendar, email, and tasks

Sim reads the creator's calendar, mail and task lists; drafts replies;
schedules and reminds; and turns "tomorrow 3pm with the plumber" into
an event, a reminder, and a house rule (unlock nothing, but turn the
porch light on). Prerequisites: platform §1–§3 (vault, OAuth,
connectors), §6 (digest), §10 (privacy). The `schedule` command and
Kernel scheduler are the reminder engine; `notify` and `home_announce`
are the outputs.

## 0. What exists

- `imaplib`/`smtplib`/`email` are stdlib; `caldav`, `icalendar`,
  `imapclient` absent.
- The Kernel scheduler fires `percept.time.scheduled`; `schedule`
  (089f73c) is its CLI; nothing creates schedules from an external
  calendar.
- No OAuth anywhere; Google/Microsoft need it (platform §2).

## 1. Open-source inventory

| component | role | notes |
|---|---|---|
| **CalDAV/CardDAV** via `caldav` + `icalendar` + `vobject` | calendars/contacts on Fastmail, iCloud, Nextcloud, Radicale, Google (CalDAV endpoint) | the one protocol that covers most providers; **the primary path** |
| **Google Calendar/Gmail/Tasks APIs** via `google-api-python-client` | when the account is Google and CalDAV is not enabled | OAuth; also a Google Workspace MCP exists |
| **Microsoft Graph** via `msgraph-sdk` or raw `httpx` | Outlook/365 | OAuth (device flow works headless) |
| **IMAP** (`imapclient` + stdlib `email`) / **JMAP** (`jmapc`, Fastmail) | mail read/search/flag/move | IMAP IDLE for push; JMAP is faster where offered |
| **SMTP** (stdlib, `aiosmtplib`) | sending | |
| **Radicale** / **Nextcloud** | self-hosted calendar/contacts/tasks if the creator wants local | a connector target |
| **Tasks**: CalDAV VTODO (Nextcloud Tasks, Apple Reminders via iCloud), Todoist API, Google Tasks, **Vikunja** (self-hosted) | one `Task` model over all | |
| **Contacts**: CardDAV | for "email Bob" resolution | |
| **`dateparser`** / `parsedatetime` | "next Tuesday at 3" → datetime | timezone-aware |
| **`recurring-ical-events`** | RRULE expansion | |
| **`mail-parser`** / stdlib | MIME, attachments → domain 1 (knowledge) index | |
| MCP: Google Workspace MCP, Outlook MCP, Todoist MCP | secondary; connectors give domain dataclasses | |

## 2. Architecture -- `simorgh/pim/` (subsystem #21, "personal information")

```
pim/
  api.py         Account, Calendar, Event, Attendee, Message, Thread, Task, Contact, FreeBusy
  config.py
  connectors/    caldav.py google.py msgraph.py imap.py jmap.py smtp.py todoist.py vikunja.py carddav.py
  sync.py        incremental sync (CalDAV sync-token / IMAP UIDVALIDITY+UID / Graph delta) into workspace/pim/pim.db
  nlp.py         date/time parsing, contact resolution, "meeting-like" detection
  reminders.py   Event/Task → Kernel schedules (percept.time.scheduled) with lead times
  triage.py      mail rules: newsletter/receipt/human/urgent classification (rules first, LLM for the rest)
  drafts.py      draft store; nothing is sent without approval (§5)
  service.py     Service: sync loop, IMAP IDLE, monitors, digest section
  fakes.py       FakeCalDAV, FakeIMAP, FakeSMTP, FakeGraph
```

`pim.db` (sqlite, vault-keyed for bodies): `events`, `tasks`,
`messages(headers only by default; bodies on demand and cached with TTL)`,
`contacts`, `sync_state`. Queryable via `query_data`
("how many meetings did I have in August").

## 3. Tools (`execution/pim.py`)

| tool | args | read_only | reversibility | Guardian |
|---|---|---|---|---|
| `cal_list` | `range` ("today", "this week", ISO), `calendar?` | yes | read_only | |
| `cal_find_time` | `duration`, `with?`, `range?`, `constraints?` | yes | read_only | free/busy across calendars |
| `cal_create` | `title`, `when`, `duration?`, `where?`, `attendees?`, `calendar?`, `remind?` | no | reversible (delete undoes) | attendees ≠ empty → **escalate** (an invite is an email) |
| `cal_update` / `cal_delete` | `event`, fields | no | reversible / irreversible if attendees | as above |
| `mail_search` | `query`, `account?`, `folder?`, `since?`, `k?` | yes | read_only | headers+snippet; bodies via `mail_read` |
| `mail_read` | `message`, `with_attachments?` | yes | read_only | body is `sensitive` → local-model routing for synthesis |
| `mail_draft` | `to`, `subject`, `body`, `reply_to?`, `account?` | no | reversible | writes a draft only |
| `mail_send` | `draft` | no | **irreversible** | **always human** (`always_human` list) unless the recipient is in `[pim] trusted_recipients` AND the rule that created it is `unattended` -- default none |
| `mail_move` / `mail_flag` / `mail_archive` | `message`, target | no | reversible | |
| `mail_unsubscribe` | `message` | no | irreversible | escalate; uses `List-Unsubscribe` header only, never a body link |
| `task_list` / `task_add` / `task_done` / `task_update` | | no | reversible | |
| `contact_find` | `query` | yes | read_only | |
| `remind` | `when`, `text`, `via?` (notify/announce/both) | no | reversible | compiles to a Kernel schedule |

Markers: `CAL_CREATE: <title>\n{"when": "tomorrow 15:00", "duration": "1h"}`;
`MAIL_DRAFT: <to>\n<subject>\n<body…>` (three-part: first line, second
line, rest -- add a `_MARKER_SPLIT_TWO_LINES` variant with a test);
`REMIND: 20m\ntake the laundry out`.

## 4. Config

```python
enabled: bool = False
accounts: tuple[AccountSpec, ...] = ()   # name, kind (caldav|google|msgraph|imap|jmap|todoist|vikunja), url, cred_id, calendars/folders include, privacy
sync_every_s: float = 300
imap_idle: bool = True
default_calendar: str = ""
default_reminder_lead: tuple = ("15m", "1d")     # for events with location: also "travel"
work_hours: str = "09:00-18:00"
timezone: str = ""                               # "" = system
trusted_recipients: tuple[str, ...] = ()         # may receive unattended mail (rule-created)
mail_body_cache_ttl_s: float = 86400
triage: bool = True
triage_llm_for_unknown: bool = True
digest_include_mail: bool = True                 # subjects/senders only
```

## 5. Guardian and privacy

- **Sending anything is human-gated** by default: `mail_send`, an
  event with attendees, `mail_unsubscribe`. `PimRule` escalates these
  regardless of auto-approve (`auto_approve_exempt_layers += "pim"`).
- Mail bodies are `sensitive`; the digest and `notify` carry
  subjects/senders only; synthesis over bodies routes per platform §10.
- Attachments are opened only through `read_file`'s existing
  doctext/pdftext path, in the sandbox roots, never executed.
- Rate: `mail_send` ≤ 20/day even when approved; `mail_move` ≤ 200/day
  (a triage rule gone wrong should not empty an inbox).
- `mail_read` on messages older than 1 year requires `confirm` (a bulk
  historical read is a different intent from triage).

## 6. Automations, triggers, monitors

- Percepts: `percept.pim.mail_received {account, from, subject, triage}`,
  `percept.pim.event_soon {event, minutes}`, `percept.pim.task_due`.
  Rules in `home`'s engine can use them (`event` trigger): "15 min
  before a meeting titled *call* → do-not-disturb scene + announce".
- Triage rules (TOML, then LLM for unknown): newsletter → archive +
  weekly digest; receipt → forward to domain 7 (finance) index;
  from a `vip` → warn-level notify with subject; calendar invite →
  `cal_*` proposal to accept/decline (human).
- Monitors: `sync_failed`, `auth_expired` (→ `vault reauth`),
  `inbox_growth` (unread > N for 3 days), `double_booked`, `no_reply`
  (a mail *from* the creator awaiting reply > 5 days -- info),
  `travel_time` (next event has a location and the previous ends too
  close; uses the geocode tool).
- Digest: today's events, tasks due, mail needing a reply (subjects),
  drafts waiting for approval.

## 7. Tests

- Each connector against its fake: incremental sync via sync-token/UID;
  a deleted remote event is tombstoned; timezones round-trip; RRULE
  expansion for weekly with exceptions.
- `nlp.py`: 40 phrases → datetimes (with DST edge cases); "with Bob"
  resolves through contacts; ambiguity ("next Friday" on a Friday)
  asks.
- Drafts never send; `mail_send` proposal is `needs_human` with
  auto-approve on; trusted-recipient path is `reversible` only when
  `proposed_by` is a rule.
- Triage: table of 30 messages → classes; unknown goes to the LLM
  once and is cached.
- Reminders become Kernel schedules and fire `percept.time.scheduled`
  with the event id; cancelling the event cancels the schedule.
- Secret never appears (token containing `SECRET`).
- End-to-end: FakeCalDAV + FakeIMAP → "when am I free tomorrow for an
  hour" → `CAL_FIND_TIME` → answer; "draft a reply to Bob saying yes"
  → draft exists, nothing sent.

## 8. Build order and acceptance

1. CalDAV + IMAP read-only + `cal_list`/`mail_search`/`mail_read` +
   sync db. Acceptance: today's real events and last 10 subjects via
   the CLI, credentials from the vault.
2. `remind` + event reminders + digest section. 3. Drafts, tasks,
   contacts, `cal_create` (no attendees). 4. Google/Graph OAuth
   connectors. 5. Triage + percepts + monitors. 6. Sending (gated),
   invites, unsubscribe.

## 9. Traps

- Google's CalDAV endpoint needs an app password or OAuth; iCloud
  needs an app-specific password; document both in `docs/setup/pim.md`.
- IMAP `UIDVALIDITY` changes mean a full resync; handle it, don't
  duplicate.
- Sent mail must be appended to the Sent folder (`APPEND`) or the
  creator's own client will never show it.
- HTML mail → text with `html2text`, quoted history stripped
  (`talon`/regex) before it reaches a prompt -- otherwise every reply
  thread is 10× the tokens.
- All-day events have no timezone; treat as local dates, not
  midnight UTC.
- `List-Unsubscribe` `mailto:` variant sends an email -- that is
  `mail_send`, gate it as such.
