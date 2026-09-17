"""The overheard log: every transcribed line that was NOT said to Sim,
kept on disk -- unknown voices, and known voices talking among themselves
-- with a timestamp and a speaker label where the voice was placed.

The room deque (`voice/session.py::_room`) is transient: sixteen lines,
gone on restart. This is the durable counterpart, for "what did we say
in the last hour?" asked hours later. It is local only, under
`workspace/voice/overheard/overheard.jsonl`, one JSON object per line:

    {"at": 1737000000.0, "speaker": "Saeed" | "someone", "text": "..."}

Entries older than `max_age_s` (default 48 h) are purged whenever the
log is opened or written; `wipe` empties it on demand.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_DIR = "workspace/voice/overheard"
DEFAULT_MAX_AGE_S = 48 * 3600.0


class OverheardLog:
    def __init__(self, folder: Path | str = DEFAULT_DIR, *, max_age_s: float = DEFAULT_MAX_AGE_S) -> None:
        self._path = Path(folder) / "overheard.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.max_age_s = float(max_age_s)
        self._entries: list[dict] = []
        self._load()

    # ------------------------------------------------------------- storage
    def _load(self) -> None:
        if not self._path.is_file():
            self._entries = []
            return
        entries: list[dict] = []
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and isinstance(entry.get("at"), (int, float)) and isinstance(entry.get("text"), str):
                    entries.append(entry)
        except OSError:
            pass
        self._entries = entries
        self._purge()

    def _flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self._entries), encoding="utf-8")
        except OSError:
            pass  # a failed write must never break the voice loop

    # ------------------------------------------------------------- writing
    def add(self, speaker: str, text: str, at: float | None = None) -> None:
        self._purge()
        self._entries.append({"at": float(at if at is not None else time.time()),
                              "speaker": speaker or "someone",
                              "text": (text or "").strip()})
        self._flush()

    # ------------------------------------------------------------ cleaning
    def _purge(self) -> None:
        cutoff = time.time() - self.max_age_s
        kept = [e for e in self._entries if float(e["at"]) >= cutoff]
        if len(kept) != len(self._entries):
            self._entries = kept
            self._flush()

    def purge(self) -> int:
        """Drop entries older than the retention window; return how many."""
        before = len(self._entries)
        self._purge()
        return before - len(self._entries)

    def wipe(self) -> int:
        """Erase the whole log on demand; return how many were removed."""
        n = len(self._entries)
        self._entries = []
        try:
            self._path.write_text("", encoding="utf-8")
        except OSError:
            pass
        return n

    # ------------------------------------------------------------ querying
    def since(self, since_s: float, *, until_s: float | None = None) -> list[dict]:
        """Entries with `since_s <= at <= until_s` (default now), oldest first."""
        until = float(until_s) if until_s is not None else time.time()
        self._purge()
        return [e for e in self._entries if since_s <= float(e["at"]) <= until]

    def lines(self, since_s: float, *, until_s: float | None = None) -> str:
        """`HH:MM speaker: text` lines for the range, oldest first."""
        return "\n".join(
            f"{time.strftime('%H:%M', time.localtime(e['at']))} {e['speaker']}: {e['text']}"
            for e in self.since(since_s, until_s=until_s))


__all__ = ["DEFAULT_DIR", "DEFAULT_MAX_AGE_S", "OverheardLog"]
