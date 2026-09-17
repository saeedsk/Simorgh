"""Overhear and voice memos -- what Sim heard that was not for Sim.

The creator, 2026-09-16: "summarize what you heard in background or what
happened during the day ... my kids are talking to each other, not to
you ... I ask you okay what happened, what I talked about, what Alice
talked about."

Two kinds of entry, one store:

* ``overheard`` -- speech Sim transcribed but did not answer: a voice
  nobody enrolled, or words the model judged were not for Sim. Filed with
  the speaker label the voice gave it (``someone`` when no voice matched)
  and the time it was heard.
* ``memo`` -- "record a memo": speech Sim was asked to keep, word for word.

Nothing here is kept long. Every entry older than ``retention_s`` (two
days) is purged on every write and every read, and ``purge_all`` empties
the store on the creator's word. Kept audio (optional) goes with its
entry. The store is plain JSON lines, one file a day, under
``workspace/voice/overhear/`` -- readable and deletable by hand.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

RETENTION_S = 2 * 24 * 3600.0
UNKNOWN = "someone"
KINDS = ("overheard", "memo")


@dataclass(frozen=True)
class Heard:
    """One overheard line or memo."""

    ts: float
    kind: str
    speaker: str
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    confidence: float = 1.0
    audio: str = ""          # a kept WAV beside the day file, or ""
    title: str = ""          # a memo's name, when one was given

    def day(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime("%Y-%m-%d")

    def clock(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime("%H:%M")


class OverhearLog:
    """The two-day store. Thread-safe; every call purges what has aged out."""

    def __init__(self, root: str | Path, *, clock: Callable[[], float] = time.time,
                 retention_s: float = RETENTION_S) -> None:
        self.root = Path(root)
        self._clock = clock
        self.retention_s = float(retention_s)
        self._lock = threading.Lock()

    # -- writing -------------------------------------------------------------
    def overheard(self, text: str, *, speaker: str = "", confidence: float = 1.0,
                  audio: bytes | None = None, ts: float | None = None) -> Heard | None:
        return self._add("overheard", text, speaker=speaker, confidence=confidence, audio=audio, ts=ts)

    def memo(self, text: str, *, speaker: str = "", title: str = "", confidence: float = 1.0,
             audio: bytes | None = None, ts: float | None = None) -> Heard | None:
        return self._add("memo", text, speaker=speaker, confidence=confidence, audio=audio, ts=ts, title=title)

    def _add(self, kind: str, text: str, *, speaker: str, confidence: float, audio: bytes | None,
             ts: float | None, title: str = "") -> Heard | None:
        text = " ".join(str(text or "").split())
        if not text:
            return None
        entry = Heard(ts=float(ts if ts is not None else self._clock()), kind=kind,
                      speaker=_label(speaker), text=text, confidence=float(confidence), title=title.strip())
        with self._lock:
            self._purge_locked()
            if entry.ts < self._clock() - self.retention_s:
                return None     # already older than we keep
            self.root.mkdir(parents=True, exist_ok=True)
            if audio:
                wav = self.root / f"{entry.day()}-{entry.id}.wav"
                wav.write_bytes(audio)
                entry = Heard(**{**asdict(entry), "audio": wav.name})
            with (self.root / f"{entry.day()}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        return entry

    # -- reading -------------------------------------------------------------
    def entries(self, *, person: str = "", day: str = "", kind: str = "") -> list[Heard]:
        """Oldest first. `person` matches the label case-insensitively;
        `day` is YYYY-MM-DD; `kind` is overheard or memo."""
        with self._lock:
            self._purge_locked()
            found = list(self._read_all())
        want = person.strip().lower()
        out = [e for e in found
               if (not want or e.speaker.lower() == want)
               and (not day or e.day() == day)
               and (not kind or e.kind == kind)]
        return sorted(out, key=lambda e: e.ts)

    def people(self, *, day: str = "") -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entries(day=day):
            counts[e.speaker] = counts.get(e.speaker, 0) + 1
        return counts

    def replay(self, *, person: str = "", day: str = "", kind: str = "") -> str:
        """Every line, word for word, with who and when."""
        rows = self.entries(person=person, day=day, kind=kind)
        if not rows:
            return _nothing(person, day, kind)
        lines, last_day = [], ""
        for e in rows:
            if e.day() != last_day:
                lines.append(f"-- {e.day()} --")
                last_day = e.day()
            tag = " (memo" + (f": {e.title}" if e.title else "") + ")" if e.kind == "memo" else ""
            lines.append(f"[{e.clock()}] {e.speaker}{tag}: {e.text}")
        return "\n".join(lines)

    def summary(self, *, person: str = "", day: str = "") -> str:
        """A short account without a model: who spoke, how much, when, and
        the gist lines. The conversational layer may hand `replay()` to the
        model for a richer summary; this one always works offline."""
        rows = self.entries(person=person, day=day)
        if not rows:
            return _nothing(person, day, "")
        by: dict[str, list[Heard]] = {}
        for e in rows:
            by.setdefault(e.speaker, []).append(e)
        span = f"{rows[0].clock()}-{rows[-1].clock()}" if rows[0].day() == rows[-1].day() else \
            f"{rows[0].day()} {rows[0].clock()} to {rows[-1].day()} {rows[-1].clock()}"
        head = f"{len(rows)} thing(s) heard" + (f" on {day}" if day else "") + f", {span}."
        out = [head]
        for who, items in sorted(by.items(), key=lambda kv: -len(kv[1])):
            memos = sum(1 for i in items if i.kind == "memo")
            gist = "; ".join(_clip(i.text) for i in _longest(items, 3))
            extra = f", {memos} memo(s)" if memos else ""
            out.append(f"- {who}: {len(items)} line(s){extra} -- {gist}")
        return "\n".join(out)

    # -- forgetting ----------------------------------------------------------
    def purge(self) -> int:
        """Drop everything older than the retention; returns how many."""
        with self._lock:
            return self._purge_locked()

    def purge_all(self, *, person: str = "", day: str = "") -> int:
        """On demand: everything, or only one person's / one day's."""
        with self._lock:
            if not self.root.exists():
                return 0
            if not person and not day:
                n = sum(1 for _ in self._read_all())
                for p in self.root.iterdir():
                    if p.suffix in (".jsonl", ".wav"):
                        p.unlink(missing_ok=True)
                return n
            want = person.strip().lower()
            return self._rewrite(lambda e: (not want or e.speaker.lower() == want) and (not day or e.day() == day))

    def _purge_locked(self) -> int:
        if not self.root.exists():
            return 0
        cutoff = self._clock() - self.retention_s
        return self._rewrite(lambda e: e.ts < cutoff)

    def _rewrite(self, drop: Callable[[Heard], bool]) -> int:
        dropped = 0
        for path in sorted(self.root.glob("*.jsonl")):
            keep, gone = [], []
            for e in _read(path):
                (gone if drop(e) else keep).append(e)
            if not gone:
                continue
            dropped += len(gone)
            for e in gone:
                if e.audio:
                    (self.root / e.audio).unlink(missing_ok=True)
            if keep:
                path.write_text("".join(json.dumps(asdict(e), ensure_ascii=False) + "\n" for e in keep),
                                encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        return dropped

    def _read_all(self) -> Iterable[Heard]:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.jsonl")):
            yield from _read(path)


# -- what the creator asks ------------------------------------------------------

@dataclass(frozen=True)
class Request:
    action: str              # memo | summary | replay | purge
    person: str = ""
    day: str = ""
    text: str = ""           # a memo's words, when said in the same breath


_MEMO = re.compile(r"^\s*(?:please\s+)?(?:record|take|make|start)\s+(?:a\s+)?(?:voice\s+)?memo\b[\s:,.-]*(?P<body>.*)$", re.I | re.S)
_PURGE = re.compile(r"\b(?:purge|delete|erase|clear|forget|wipe)\b.*\b(?:overheard|heard|memos?|background|recordings?)\b", re.I)
_REPLAY = re.compile(r"\b(?:replay|play back|word for word|exactly what|read back|transcript)\b", re.I)
_SUMMARY = re.compile(r"\b(?:summar\w*|what (?:did|has|have) .{0,40}?(?:say|said|talk\w*)|what happened|what did you hear|what was said)\b", re.I)
_PERSON = re.compile(r"\b(?:what (?:did|has)|from|by|of|for)\s+(?P<name>[A-Z][a-z]+)\b")
_NOT_NAMES = {"Sim", "Simorgh", "Today", "Yesterday", "The", "Everyone", "Me", "I"}


def parse_request(text: str, *, now: float | None = None) -> Request | None:
    """Recognise an overhear/memo ask, or None when it is not one."""
    s = str(text or "").strip()
    if not s:
        return None
    m = _MEMO.match(s)
    if m:
        return Request("memo", text=m.group("body").strip())
    day = _day_in(s, now)
    person = _person_in(s)
    if _PURGE.search(s):
        return Request("purge", person=person, day=day)
    if _REPLAY.search(s):
        return Request("replay", person=person, day=day)
    if _SUMMARY.search(s):
        return Request("summary", person=person, day=day)
    return None


def answer(log: OverhearLog, request: Request, *, speaker: str = "") -> str:
    """Carry out a parsed ask against the store and say what happened."""
    if request.action == "memo":
        if not request.text:
            return "Go ahead -- I'm recording your memo."
        log.memo(request.text, speaker=speaker)
        return "Memo kept (for two days)."
    if request.action == "purge":
        n = log.purge_all(person=request.person, day=request.day)
        return f"Forgot {n} thing(s) I had heard."
    if request.action == "replay":
        return log.replay(person=request.person, day=request.day)
    return log.summary(person=request.person, day=request.day)


# -- helpers ----------------------------------------------------------------------

def _label(speaker: str) -> str:
    s = str(speaker or "").strip()
    return s if s else UNKNOWN


def _read(path: Path) -> Iterable[Heard]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            raw = json.loads(line)
            yield Heard(**{k: raw[k] for k in raw if k in Heard.__dataclass_fields__})
        except (ValueError, TypeError, KeyError):
            continue    # a torn line is skipped, not fatal


def _nothing(person: str, day: str, kind: str) -> str:
    what = "memos" if kind == "memo" else "anything"
    who = f" from {person}" if person else ""
    when = f" on {day}" if day else " in the last two days"
    return f"I haven't kept {what}{who}{when}."


def _clip(text: str, n: int = 90) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _longest(items: list[Heard], k: int) -> list[Heard]:
    top = sorted(items, key=lambda e: -len(e.text))[:k]
    return sorted(top, key=lambda e: e.ts)


def _day_in(text: str, now: float | None) -> str:
    base = datetime.fromtimestamp(now if now is not None else time.time())
    low = text.lower()
    if "yesterday" in low:
        return (base - timedelta(days=1)).strftime("%Y-%m-%d")
    if "today" in low or "this morning" in low or "tonight" in low:
        return base.strftime("%Y-%m-%d")
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    return m.group(1) if m else ""


def _person_in(text: str) -> str:
    for m in _PERSON.finditer(text):
        name = m.group("name")
        if name not in _NOT_NAMES:
            return name
    return ""


__all__ = ["KINDS", "RETENTION_S", "UNKNOWN", "Heard", "OverhearLog", "Request", "answer", "parse_request"]
