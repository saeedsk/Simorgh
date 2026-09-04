"""Short-term context window: a bounded, in-memory record of the most
recent turns, for cognition calls that need recent context (a future
LLM-backed CognitionRouter call) without re-deriving it from long-term
memory every time. Distinct from src/memory/long_term.py: this is
intentionally NOT durable -- it resets with the process, the way a
person's working memory doesn't survive the way consolidated long-term
memories do. See docs/BIOMIMICRY.md, "Sleep."
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Turn:
    request_text: str
    response_text: str
    timestamp: float = field(default_factory=time.time)


class ShortTermMemory:
    """A bounded rolling window of recent turns.

    Bounded two ways: at most `max_turns` entries, and at most
    `max_chars` total characters across all entries (oldest dropped
    first) -- a rough, dependency-free stand-in for a token budget, since
    no tokenizer is wired in yet. At least one turn is always kept, even
    if it alone exceeds `max_chars`.
    """

    def __init__(self, max_turns: int = 20, max_chars: int = 8000) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        self._max_turns = max_turns
        self._max_chars = max_chars
        self._turns: deque[Turn] = deque()

    def add(self, request_text: str, response_text: str) -> Turn:
        turn = Turn(request_text=request_text, response_text=response_text)
        self._turns.append(turn)
        self._trim()
        return turn

    def recent(self, limit: int | None = None) -> list[Turn]:
        """Oldest first -- the natural reading order for a transcript."""
        turns = list(self._turns)
        return turns[-limit:] if limit is not None else turns

    def as_context(self, limit: int | None = None) -> str:
        """Render recent turns as a plain-text transcript, suitable for
        prefixing a cognition prompt.
        """
        lines = []
        for turn in self.recent(limit):
            lines.append(f"User: {turn.request_text}")
            lines.append(f"Sim: {turn.response_text}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._turns.clear()

    def save(self, path: Path) -> None:
        """Persist the current window to `path` as JSON. This exists for
        exactly one purpose: self_patch.relaunch's os.execv wipes this
        in-memory object outright, so a patch/evolve relaunch used to
        silently drop the whole conversation the creator was mid-way
        through -- a real gap Sim identified about its own architecture.
        Called right before a relaunch, paired with load_and_clear()
        called once on the next process's startup. Best-effort: a write
        failure here must never block a relaunch that already passed
        every safety gate.
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = [
                {
                    "request_text": t.request_text,
                    "response_text": t.response_text,
                    "timestamp": t.timestamp,
                }
                for t in self._turns
            ]
            path.write_text(json.dumps(payload))
        except OSError:
            pass

    @classmethod
    def load_and_clear(
        cls, path: Path, max_turns: int = 20, max_chars: int = 8000
    ) -> "ShortTermMemory | None":
        """Load a window saved by save(path), then delete the file --
        a one-shot handoff across exactly one relaunch, not a durable
        log (that's long_term.py's job). Deleting it is deliberate: a
        stale file left behind by a crash must never silently reappear
        in some later, unrelated session. Returns None (no restore) if
        the file is missing or unreadable -- corruption here must never
        crash startup.
        """
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        memory = cls(max_turns=max_turns, max_chars=max_chars)
        if not isinstance(payload, list):
            return None
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            request_text = entry.get("request_text")
            response_text = entry.get("response_text")
            if not isinstance(request_text, str) or not isinstance(response_text, str):
                continue
            timestamp = entry.get("timestamp")
            memory._turns.append(
                Turn(
                    request_text=request_text,
                    response_text=response_text,
                    timestamp=timestamp if isinstance(timestamp, (int, float)) else time.time(),
                )
            )
        memory._trim()
        return memory

    def __len__(self) -> int:
        return len(self._turns)

    def _trim(self) -> None:
        while len(self._turns) > self._max_turns:
            self._turns.popleft()
        while self._total_chars() > self._max_chars and len(self._turns) > 1:
            self._turns.popleft()

    def _total_chars(self) -> int:
        return sum(len(t.request_text) + len(t.response_text) for t in self._turns)
