"""What Sim heard that was not said to Sim, and what it was told to keep.

The creator, 2026-09-16, in his own words: "for the voices that you
don't recognize, or you recognize but you understand this is not
directed to you -- can you keep track of them for one day, two days,
and when I ask you, summarize or replay them, and then after one or two
days purge them." And a minute later: "you will have a voice memo
capability. Sometimes I directly tell you to capture my voice."

This was built twice that afternoon and worked neither time.

`voice/overheard.py` recorded every line and could not be asked
anything: nothing in `commands.py` or `session.py` ever mentioned
summarize, replay or wipe, so its `since()` and `lines()` were dead
ends. `voice/overhear.py` had the whole query surface -- summaries,
replay, memos, even a natural-language request parser -- and was
imported by nothing at all, 313 lines of unreachable code. Two tasks,
about $3, and the feature recorded but could not answer.

Both sat in `simorgh/voice/`, and that is precisely why. The tool that
answers "what did you hear?" runs in Execution, and no subsystem may
import another -- so a store in Voice can be written by Voice and read
by nobody. The read half was never going to reach it.

So it lives here, for the same reason `console.py` and `places.py` do:
Voice records, Execution's `overheard` tool reads, and neither needs to
know the other exists.

Kept 48 hours by default and purged on every write, because the
creator asked for one or two days and because a recording of a family's
kitchen should expire without anyone having to remember to delete it.
`wipe()` is the deliberate version, for when someone wants it gone now.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

#: Where the lines live: gitignored scratch, one JSON object per line,
#: readable and deletable by hand without this module's help.
DEFAULT_DIR = Path("workspace/voice/overheard")
FILE_NAME = "heard.jsonl"

#: Two days, as asked. Purged on write, so it needs no scheduler.
MAX_AGE_S = 48 * 3600.0

#: Below this an `at` cannot be a wall clock (2001-09-09), so it is one.
EPOCH_FLOOR = 1.0e9

#: `overheard` is speech that was not for Sim. `memo` is speech someone
#: asked Sim to keep on purpose. They share a store because "what did I
#: say this morning?" should find both, and differ by one field because
#: "play back my memos" should find only one.
KINDS = ("overheard", "memo", "said")

#: A silence longer than this ends a conversation and the next line
#: starts a new one. The creator, 2026-09-16: "keep track of overheard,
#: and separate them to different groups of overheard conversation that
#: are relevant to each other." Three minutes, because a kitchen
#: exchange pauses while somebody crosses the room, and an hour later is
#: plainly a different conversation.
THREAD_GAP_S = 180.0

_lock = threading.Lock()


def heard_path(folder: Path | str | None = None) -> Path:
    return Path(folder or DEFAULT_DIR) / FILE_NAME


def record(text: str, *, speaker: str = "", kind: str = "overheard",
           at: float | None = None, folder: Path | str | None = None) -> bool:
    """Keep one line. True if it was written. Never raises.

    Never raises because this is called from the voice loop for every
    line the room says, and a log that could break listening would be a
    strictly worse system than one that occasionally forgets.
    """
    words = " ".join(str(text or "").split())
    if not words:
        return False
    # An `at` below the floor is a monotonic clock, not a wall one. Voice
    # passed `time.monotonic()` here on 2026-09-16 and every line became
    # unrecallable; this store is read by two subsystems and the next caller
    # would make the same mistake, so it is corrected here rather than trusted.
    stamp = float(at) if at is not None else time.time()
    if stamp < EPOCH_FLOOR:
        stamp = time.time()
    entry = {"at": stamp,
             "speaker": " ".join(str(speaker or "").split()) or "someone",
             "text": words[:2000],
             "kind": kind if kind in KINDS else "overheard"}
    path = heard_path(folder)
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Which conversation this belongs to, decided by the silence
            # before it rather than by anything in the words: a gap longer
            # than `THREAD_GAP_S` means the room moved on.
            existing = _read(path)
            previous = existing[-1] if existing else None
            thread = 1
            if previous is not None:
                thread = int(previous.get("thread") or 1)
                if entry["at"] - float(previous.get("at") or 0.0) > THREAD_GAP_S:
                    thread += 1
            entry["thread"] = thread
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _purge_locked(path, now=entry["at"])
        return True
    except OSError:
        return False


def _read(path: Path) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict) and item.get("text"):
            out.append(item)
    return out


def _purge_locked(path: Path, *, now: float, max_age_s: float = MAX_AGE_S) -> int:
    items = _read(path)
    keep = [i for i in items if now - float(i.get("at") or 0.0) <= max_age_s]
    if len(keep) == len(items):
        return 0
    _write_all(path, keep)
    return len(items) - len(keep)


def _write_all(path: Path, items: list[dict]) -> None:
    tmp = path.with_suffix(".jsonl.part")
    tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    os.replace(tmp, path)


def purge(*, now: float | None = None, max_age_s: float = MAX_AGE_S,
          folder: Path | str | None = None) -> int:
    """Drop what has aged out. Returns how many went."""
    path = heard_path(folder)
    try:
        with _lock:
            return _purge_locked(path, now=now if now is not None else time.time(), max_age_s=max_age_s)
    except OSError:
        return 0


def recall(*, since_s: float | None = None, speaker: str = "", kind: str = "",
           limit: int = 200, now: float | None = None,
           folder: Path | str | None = None) -> list[dict]:
    """The lines that match, oldest first.

    `since_s` is an age in seconds, not a timestamp: "the last hour" is
    what a person asks for, and the caller should not have to do clock
    arithmetic to ask it.
    """
    moment = now if now is not None else time.time()
    items = _read(heard_path(folder))
    who = " ".join(str(speaker or "").split()).lower()
    if since_s is not None:
        items = [i for i in items if moment - float(i.get("at") or 0.0) <= float(since_s)]
    if who:
        items = [i for i in items if who in str(i.get("speaker") or "").lower()]
    if kind:
        items = [i for i in items if str(i.get("kind") or "") == kind]
    items.sort(key=lambda i: float(i.get("at") or 0.0))
    return items[-max(1, int(limit)):]


def transcript(items: list[dict]) -> str:
    """`09:14  Ira: it isn't fair that you get pizza` -- one line each."""
    out = []
    for item in items:
        stamp = time.strftime("%H:%M", time.localtime(float(item.get("at") or 0.0)))
        mark = "memo" if item.get("kind") == "memo" else str(item.get("speaker") or "someone")
        out.append(f"{stamp}  {mark}: {item.get('text')}")
    return "\n".join(out)


def speakers(items: list[dict]) -> dict[str, int]:
    """Who said how much, for "what did the kids talk about?"."""
    counts: dict[str, int] = {}
    for item in items:
        name = str(item.get("speaker") or "someone")
        counts[name] = counts.get(name, 0) + 1
    return counts


def conversations(items: list[dict]) -> list[dict]:
    """The lines grouped into the exchanges they belong to.

    A flat transcript answers "what was said"; a person asking "what did
    they talk about" means the separate conversations, each with who was
    in it and when it ran.
    """
    groups: dict[int, list[dict]] = {}
    for item in items:
        groups.setdefault(int(item.get("thread") or 1), []).append(item)
    out = []
    for thread, lines in sorted(groups.items()):
        lines.sort(key=lambda i: float(i.get("at") or 0.0))
        out.append({
            "thread": thread,
            "started": float(lines[0].get("at") or 0.0),
            "ended": float(lines[-1].get("at") or 0.0),
            "speakers": sorted({str(i.get("speaker") or "someone") for i in lines}),
            "lines": lines,
        })
    return out


def wipe(*, speaker: str = "", kind: str = "", folder: Path | str | None = None) -> int:
    """Delete now, rather than waiting for the age to do it.

    With no argument it empties the store. That bluntness is the point:
    someone who says "forget what you heard" means all of it, and having
    to name a person first would be a worse answer than doing it.
    """
    path = heard_path(folder)
    who = " ".join(str(speaker or "").split()).lower()
    try:
        with _lock:
            items = _read(path)
            if not items:
                return 0
            keep = []
            for item in items:
                matches = ((not who or who in str(item.get("speaker") or "").lower())
                           and (not kind or str(item.get("kind") or "") == kind))
                if not matches:
                    keep.append(item)
            if len(keep) == len(items):
                return 0
            _write_all(path, keep)
            return len(items) - len(keep)
    except OSError:
        return 0


__all__ = ["DEFAULT_DIR", "EPOCH_FLOOR", "FILE_NAME", "KINDS", "MAX_AGE_S", "THREAD_GAP_S",
           "conversations", "heard_path", "purge",
           "recall", "record", "speakers", "transcript", "wipe"]
