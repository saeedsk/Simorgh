"""Short-term context window: a bounded, in-memory record of the most
recent turns, for cognition calls that need recent context (a future
LLM-backed CognitionRouter call) without re-deriving it from long-term
memory every time. Distinct from src/memory/long_term.py: this is
intentionally NOT durable -- it resets with the process, the way a
person's working memory doesn't survive the way consolidated long-term
memories do. See docs/BIOMIMICRY.md, "Sleep."
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


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

    def __len__(self) -> int:
        return len(self._turns)

    def _trim(self) -> None:
        while len(self._turns) > self._max_turns:
            self._turns.popleft()
        while self._total_chars() > self._max_chars and len(self._turns) > 1:
            self._turns.popleft()

    def _total_chars(self) -> int:
        return sum(len(t.request_text) + len(t.response_text) for t in self._turns)
