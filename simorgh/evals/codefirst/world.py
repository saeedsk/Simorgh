"""The household's data, made up the same way every time (stage 19 item 8).

One `World` per (seed, anchor day): a mailbox, a calendar, a file index
and a tool-telemetry log, each larger than any one tool page can show.
Everything is drawn from `random.Random(seed)` and placed relative to
`anchor` (the day the run happens), so the same seed on the same day is
the same household, and the expected answers are computed from this
data and nothing else (`cases.py`).

The shapes are chosen so that reading a page gives a *wrong* answer,
not just an unproven one:

- mail: the five biggest senders of the month send early in it, and
  four small senders burst in its last days, so the newest page is
  dominated by the wrong names;
- calendar: a quarter of meetings, in date order, so the first page
  covers only the first weeks;
- files: the index is sorted by path, and size has nothing to do with
  path, so the first lines hold a random handful of the largest;
- telemetry: ten days of tool calls, three of them outside the asked
  week, sorted by time, so the first page is the wrong days.

Where Sim's tools read them (`install`): the mailbox and the calendar
through the real `mail_search` / `mail_read` / `cal_list`, given a
connector (the domain tests' seam, `_PimTool(connectors=)`); the file
index and the telemetry log as files in the workspace, through the real
`read_file`. Sim has no tool that stats a file, so the file domain is
the index a `find -printf '%s\\t%p\\n'` would write -- the data a
household file question is about, in the form Sim can reach.

`domains/pim/connectors/fakes.py::FakeImapServer` ignores `SINCE`, and
a month's question over a mailbox that answers every search with every
message would be testing the fake. `_Mailbox` below is that server with
`SINCE` honoured, built here because the domain fake is not this
package's to change.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

#: The seed every suite run uses unless told otherwise. A different seed
#: is a different household with the same shape.
DEFAULT_SEED = 19

#: The day the offline tests pretend it is. The Sim run uses today, so
#: that "the last 30 days" in a question and in Sim's tools agree.
TEST_ANCHOR = date(2026, 10, 28)

#: Where the file index and the telemetry log go, relative to the repo
#: root Sim's `read_file` resolves against (`workspace/` is readable).
WORKSPACE_DIR = "workspace/codefirst"
FILES_INDEX = f"{WORKSPACE_DIR}/files.txt"
TELEMETRY_LOG = f"{WORKSPACE_DIR}/telemetry.jsonl"

#: The account name the mailbox and the calendar are given to the tools as.
ACCOUNT = "home"

#: How many days back the mail window and the telemetry window reach.
MAIL_DAYS = 30
TELEMETRY_DAYS = 7
#: The calendar quarter: the 90 days after the anchor.
QUARTER_DAYS = 90


# ------------------------------------------------------------------ the people
_FIRST = ("Parisa", "Dariush", "Mina", "Kaveh", "Leila", "Bijan", "Shirin", "Farhad", "Nasrin", "Omid",
          "Roya", "Babak", "Taraneh", "Kamran", "Yasmin", "Arash", "Golnar", "Navid", "Setareh", "Ramin",
          "Elham", "Payam", "Azadeh", "Siavash", "Mahsa", "Behzad", "Ladan", "Pouya", "Neda", "Kourosh")
_LAST = ("Tehrani", "Shirazi", "Kermani", "Rahimi", "Farahani", "Kashani", "Tabrizi", "Yazdi", "Hosseini",
         "Moradi", "Ahmadi", "Karimi", "Jafari", "Sadeghi", "Rostami", "Nouri", "Bahrami", "Ghorbani")
_SERVICES = (
    ("Daily Deals", "deals@shopnest.example"), ("Weekend Flyer", "flyer@grocerly.example"),
    ("Fresh Basket", "hello@freshbasket.example"), ("Trailhead Outdoor", "news@trailhead.example"),
    ("Bright Utilities", "billing@brightpower.example"), ("Maple School", "office@maple-school.example"),
    ("Cineplex Club", "club@cineplex.example"), ("Roam Travel", "offers@roamtravel.example"),
    ("City Library", "notices@citylib.example"), ("Pixel Bank", "alerts@pixelbank.example"),
    ("Sprout Kids", "team@sproutkids.example"), ("Harbor Dental", "care@harbordental.example"),
    ("Tune Box", "hi@tunebox.example"), ("Gadget Hub", "promo@gadgethub.example"),
    ("Book Nook", "letters@booknook.example"), ("Swift Courier", "track@swiftcourier.example"),
    ("Neighbour Net", "digest@neighbournet.example"), ("Green Thumb", "garden@greenthumb.example"),
    ("Daily Brief", "brief@dailybrief.example"), ("Fit Studio", "classes@fitstudio.example"),
)


@dataclass(frozen=True)
class Sender:
    name: str
    address: str

    @property
    def header(self) -> str:
        return f"{self.name} <{self.address}>"


@dataclass
class World:
    """One household's data, and where it came from."""

    seed: int
    anchor: date
    senders: list[Sender] = field(default_factory=list)
    #: `FakeImapServer` message specs, oldest first, uid = position + 1.
    mail: list[dict] = field(default_factory=list)
    #: `domains.pim.api.Event`s, in date order.
    events: list = field(default_factory=list)
    #: (size in bytes, path), sorted by path as `find | sort` would.
    files: list[tuple[int, str]] = field(default_factory=list)
    #: One dict per tool call: ts (ISO, UTC), tool, ok, error_kind, ms.
    telemetry: list[dict] = field(default_factory=list)
    #: The 25 senders the per-item question names, in the order it names them.
    named: list[Sender] = field(default_factory=list)

    # -- the windows the questions ask about --------------------------------------------
    @property
    def mail_since(self) -> date:
        return self.anchor - timedelta(days=MAIL_DAYS)

    @property
    def mail_until(self) -> date:
        return self.anchor - timedelta(days=1)

    @property
    def quarter(self) -> tuple[date, date]:
        return self.anchor + timedelta(days=1), self.anchor + timedelta(days=QUARTER_DAYS)

    @property
    def telemetry_window(self) -> tuple[date, date]:
        return self.anchor - timedelta(days=TELEMETRY_DAYS), self.anchor - timedelta(days=1)

    # -- how Sim's tools reach it -----------------------------------------------------------
    def mailbox(self):
        """A real `ImapConnector` over this mailbox -- the real parsing,
        a fake socket."""
        from simorgh.domains.pim.connectors.imap import ImapConnector

        server = _Mailbox(messages=[dict(m) for m in self.mail])
        connector = ImapConnector(name=ACCOUNT, host="imap.fake", username="me@fake", password="app-password",
                                  client_factory=lambda: server)
        connector.server = server
        return connector

    def calendar(self):
        from simorgh.domains.pim.connectors.fakes import FakeCalDav

        return FakeCalDav(ACCOUNT, events=list(self.events))

    def install(self, root: str | Path) -> list[Path]:
        """Write the file index and the telemetry log under `root`
        (the repo root `read_file` resolves against). Returns the paths."""
        root = Path(root)
        index, log = root / FILES_INDEX, root / TELEMETRY_LOG
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(self.files_index_text(), encoding="utf-8")
        log.write_text(self.telemetry_text(), encoding="utf-8")
        return [index, log]

    def files_index_text(self) -> str:
        head = "# size_bytes\tpath -- every file under ~/Household, from find -type f -printf '%s\\t%p\\n' | sort -k2\n"
        return head + "".join(f"{size}\t{path}\n" for size, path in self.files)

    def telemetry_text(self) -> str:
        return "".join(json.dumps(row, sort_keys=True) + "\n" for row in self.telemetry)


class _Mailbox:
    """`FakeImapServer` with `SINCE` honoured (see the module docstring).

    A subclass made lazily, so importing this module does not import the
    pim domain."""

    def __new__(cls, *args, **kwargs):
        from simorgh.domains.pim.connectors.fakes import FakeImapServer

        class Mailbox(FakeImapServer):
            def _matching(self, criteria):
                out = super()._matching(criteria)
                items = [str(c) for c in criteria]
                if "SINCE" in items and items.index("SINCE") + 1 < len(items):
                    since = datetime.strptime(items[items.index("SINCE") + 1], "%d-%b-%Y").date()
                    out = [m for m in out if m["date"].astimezone(timezone.utc).date() >= since]
                return out

        return Mailbox(*args, **kwargs)


# ------------------------------------------------------------------ building it
def build(seed: int = DEFAULT_SEED, anchor: date | None = None) -> World:
    """The household for `seed` on `anchor` (default: today)."""
    anchor = anchor or date.today()
    rng = random.Random(seed)
    world = World(seed=seed, anchor=anchor)
    _people(world, rng)
    _mail(world, rng)
    _calendar(world, rng)
    _files(world, rng)
    _telemetry(world, rng)
    return world


def _people(world: World, rng: random.Random) -> None:
    names = [f"{a} {b}" for a in _FIRST for b in _LAST]
    rng.shuffle(names)
    people = []
    for full in names[:40]:
        first, last = full.split()
        people.append(Sender(full, f"{first.lower()}.{last.lower()}@mail.example"))
    world.senders = [Sender(n, a) for n, a in _SERVICES] + people


def _at(day: date, rng: random.Random) -> datetime:
    """Some moment of `day` between 12:00 and 20:00 UTC: the same calendar
    date in every timezone from UTC-11 to UTC+3, so no question's answer
    turns on where the reader is."""
    return datetime.combine(day, time(12, 0), tzinfo=timezone.utc) + timedelta(seconds=rng.randrange(8 * 3600))


_SUBJECTS = ("Your weekly update", "This week only", "Reminder", "New for you", "Receipt", "Notice",
             "Quick question", "Re: the weekend", "Photos", "Plans for Saturday", "Invoice", "Hello")


def _mail(world: World, rng: random.Random) -> None:
    """~1000 messages in the 30-day window and ~300 before it."""
    senders = list(world.senders)
    big, bursts, rest = senders[:5], senders[5:9], senders[9:44]
    only_older = senders[44:]
    window_days = [world.anchor - timedelta(days=d) for d in range(1, MAIL_DAYS + 1)]
    early = [d for d in window_days if (world.anchor - d).days >= 12]
    specs: list[tuple[Sender, datetime]] = []
    # The five that really send the most, mostly early in the month.
    for sender, count in zip(big, (97, 86, 75, 64, 53)):
        for _ in range(count):
            specs.append((sender, _at(rng.choice(early if rng.random() < 0.9 else window_days), rng)))
    # Four small senders that burst in the last days: what a newest-first
    # page is full of.
    for sender in bursts:
        for _ in range(rng.randint(26, 32)):
            day = world.anchor - timedelta(days=rng.randint(1, 3))
            specs.append((sender, _at(day, rng)))
    # Everybody else, spread over the month.
    for sender in rest:
        for _ in range(rng.randint(8, 22)):
            specs.append((sender, _at(rng.choice(window_days), rng)))
    # Before the window: everyone a little, and a few who wrote only then.
    for sender in senders:
        for _ in range(rng.randint(1, 5) if sender not in only_older else rng.randint(3, 8)):
            day = world.anchor - timedelta(days=rng.randint(MAIL_DAYS + 2, 90))
            specs.append((sender, _at(day, rng)))
    specs.sort(key=lambda s: s[1])
    world.mail = [{"uid": i + 1, "from": sender.header, "subject": rng.choice(_SUBJECTS), "date": when,
                   "folder": "INBOX", "flags": ["\\Seen"] if rng.random() < 0.8 else []}
                  for i, (sender, when) in enumerate(specs)]
    # The per-item question: 25 senders, some busy, some quiet, some who
    # wrote only before the month, in an order that is none of those.
    pool = big[:3] + bursts[:2] + rest[:14] + only_older[:6]
    rng.shuffle(pool)
    world.named = pool[:25]


_MEETINGS = ("Standup", "1:1", "Design review", "Planning", "Client call", "Dentist", "School meeting",
             "Budget", "Sync", "Interview", "Retro", "Workshop")


def _calendar(world: World, rng: random.Random) -> None:
    """A quarter of timed meetings, a few all-day events among them."""
    from simorgh.domains.pim.api import Event

    first, last = world.quarter
    events = []
    day = first
    n = 0
    while day <= last:
        weekday = day.weekday()
        count = rng.randint(3, 8) if weekday < 5 else (rng.randint(0, 2) if weekday == 5 else 0)
        for _ in range(count):
            start = datetime.combine(day, time(9, 0)) + timedelta(minutes=30 * rng.randrange(16))
            minutes = rng.choice((15, 30, 30, 45, 60, 60, 60, 90, 120))
            n += 1
            events.append(Event(uid=f"ev-{n}", summary=rng.choice(_MEETINGS), start=start,
                                end=start + timedelta(minutes=minutes), calendar=ACCOUNT))
        if rng.random() < 0.06:
            n += 1
            start = datetime.combine(day, time(0, 0))
            events.append(Event(uid=f"ev-{n}", summary=rng.choice(("Holiday", "Conference", "Away")),
                                start=start, end=start + timedelta(days=1), calendar=ACCOUNT, all_day=True))
        day += timedelta(days=1)
    events.sort(key=lambda e: (e.start, e.summary))
    world.events = events


#: (extension, how many, typical size in bytes, spread)
_FILE_TYPES = (("jpg", 1150, 2_400_000, 0.6), ("png", 300, 600_000, 0.9), ("pdf", 420, 350_000, 1.1),
               ("mp4", 160, 180_000_000, 0.9), ("docx", 220, 90_000, 0.8), ("mp3", 400, 6_000_000, 0.4),
               ("txt", 200, 4_000, 1.2), ("zip", 60, 40_000_000, 1.3), ("heic", 90, 1_800_000, 0.4))
_FOLDERS = {"jpg": ("Photos/{year}", "Photos/{year}/Trips", "Phone/Camera"), "png": ("Screenshots", "Documents/Scans"),
            "pdf": ("Documents/Bills", "Documents/School", "Documents/Taxes/{year}", "Downloads"),
            "mp4": ("Videos/{year}", "Phone/Camera"), "docx": ("Documents/Work", "Documents/School"),
            "mp3": ("Music/Albums", "Music/Podcasts"), "txt": ("Documents/Notes", "Downloads"),
            "zip": ("Backups", "Downloads"), "heic": ("Phone/Camera",)}


def _files(world: World, rng: random.Random) -> None:
    """About 3000 files: (size, path), every basename unique."""
    import math

    out = []
    serial = 1000
    for ext, count, typical, spread in _FILE_TYPES:
        for _ in range(count):
            serial += rng.randint(1, 7)
            folder = rng.choice(_FOLDERS[ext]).format(year=rng.randint(2016, 2026))
            stem = {"jpg": "IMG", "heic": "IMG", "png": "Screen", "mp4": "VID", "pdf": "Doc",
                    "docx": "Draft", "mp3": "Track", "txt": "Note", "zip": "Archive"}[ext]
            size = max(64, int(typical * math.exp(rng.gauss(0.0, spread))))
            out.append((size, f"~/Household/{folder}/{stem}_{serial}.{ext}"))
    out.sort(key=lambda row: row[1])
    world.files = out


_TOOLS = (("mail_search", 0.04), ("cal_list", 0.02), ("home_call", 0.07), ("home_state", 0.01),
          ("web_search", 0.10), ("web_fetch", 0.14), ("read_file", 0.03), ("run_python_sandboxed", 0.09),
          ("notify", 0.05), ("media_play", 0.12), ("cast_play", 0.16), ("kb_search", 0.0),
          ("remind", 0.03), ("cam_snapshot", 0.08))
_KINDS = ("transient", "failed", "refused", "unconfigured")


def _telemetry(world: World, rng: random.Random) -> None:
    """Ten days of tool calls, ~450 a day, the last ten days before the
    anchor; the question asks about the last seven."""
    rows = []
    tools = [t for t, _ in _TOOLS]
    rates = dict(_TOOLS)
    weights = [rng.uniform(0.5, 3.0) for _ in tools]
    for back in range(1, TELEMETRY_DAYS + 4):
        day = world.anchor - timedelta(days=back)
        for _ in range(rng.randint(380, 520)):
            tool = rng.choices(tools, weights=weights)[0]
            # `kb_search` never fails in the asked week, only before it:
            # a count over the whole log names it, a count over the week
            # does not.
            rate = rates[tool] if tool != "kb_search" else (0.2 if back > TELEMETRY_DAYS else 0.0)
            ok = rng.random() >= rate
            when = datetime.combine(day, time(0, 0), tzinfo=timezone.utc) + timedelta(seconds=rng.randrange(86400))
            rows.append({"ts": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "tool": tool, "ok": ok,
                         "error_kind": "" if ok else rng.choice(_KINDS), "ms": rng.randint(5, 4000)})
    rows.sort(key=lambda r: r["ts"])
    world.telemetry = rows


__all__ = ["ACCOUNT", "DEFAULT_SEED", "FILES_INDEX", "MAIL_DAYS", "QUARTER_DAYS", "Sender", "TELEMETRY_DAYS",
           "TELEMETRY_LOG", "TEST_ANCHOR", "WORKSPACE_DIR", "World", "build"]
