"""Proactive socializing: Sim surfaces an interesting, already-fetched
news item to the creator on its own, during an idle autonomous tick,
instead of only ever replying to a request -- the direct answer to
"Sim should be able to start the conversation... instead of being
reactive." Built on the same "print between blocking input() calls"
pattern src/orchestrator/reminders.py already established works safely
alongside the interactive CLI loop.

Layered on top of (never instead of) AutonomyController's own idle/
cooldown/daily-cap/circuit-breaker gates -- everything here only ever
runs from inside an already-gated autonomous tick, or a directly-typed
command. This module adds one more, usually-longer pacing cooldown of
its own so sharing a highlight doesn't dominate every idle tick at the
expense of ordinary self-improvement work; the two compete for the same
idle ticks, this only decides which one "wins" a given one.

The knowledge base itself lives in src/agents/interests.py
(InterestTracker's news_item/news_item_shared records) -- this module
only owns pacing (when to share) and drafting (how to phrase it), kept
separate and print-free so both stay unit-testable without capturing
stdout; src/main.py owns the actual printing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.agents.interests import InterestTracker
from src.cognition.provider import CognitionRouter, ProviderUnavailable
from src.memory.long_term import MemoryRecord

# Once an hour by default -- deliberately much longer than
# AutonomyController's own action_cooldown_seconds (10 min default), so
# a proactive share is an occasional, welcome interruption, not
# something competing to win every idle tick.
DEFAULT_SHARE_COOLDOWN_SECONDS = 3600.0


@dataclass(frozen=True)
class NewsHighlight:
    title: str
    blurb: str
    source: str
    topic: str


_HIGHLIGHT_PROMPT = """You're Sim, about to proactively share one interesting news item with \
the person you work with -- they didn't ask for this right now, you're bringing it to them \
because you thought it was worth mentioning. Write ONE short (1-3 sentence), warm, \
conversational highlight in your own voice -- say what it is and why it might actually \
interest them, not a dry summary. No markdown, no headers, no preamble like "Here's a \
highlight:" -- just the message itself, as you'd actually say it.

Title: {title}
Source: {source}
Raw description: {summary}"""


class NewsSocializer:
    """Owns the pacing and the drafting for proactively sharing one news
    highlight at a time out of InterestTracker's knowledge base.
    """

    def __init__(self, cooldown_seconds: float = DEFAULT_SHARE_COOLDOWN_SECONDS) -> None:
        self._cooldown_seconds = cooldown_seconds
        self._last_shared_at = 0.0

    def ready(self) -> bool:
        return time.time() - self._last_shared_at >= self._cooldown_seconds

    def maybe_share(
        self, interests: InterestTracker, cognition: CognitionRouter | None
    ) -> NewsHighlight | None:
        """The autonomous-tick path: only does anything if `ready()`.
        Returns None otherwise, or if `share_next` finds nothing.
        """
        if not self.ready():
            return None
        return self.share_next(interests, cognition)

    def share_next(
        self, interests: InterestTracker, cognition: CognitionRouter | None
    ) -> NewsHighlight | None:
        """Unconditional -- no pacing check. Used by `maybe_share` (the
        autonomous path, once it's already decided this tick is ready)
        and directly by main.py's typed `news` command, the same way
        typing `work` bypasses AutonomyController's own idle check.
        Refreshes the most-overdue tracked interest first if nothing
        unshared is already known. Marks whatever it returns as shared
        and resets the pacing clock either way it was reached. Returns
        None if nothing is tracked, or refreshing turned up nothing new.
        """
        record = _next_unshared(interests)
        if record is None:
            overdue = interests.least_recently_followed_up()
            if overdue is None:
                return None
            interests.follow_up(overdue.topic)
            record = _next_unshared(interests)
            if record is None:
                return None

        interests.mark_news_item_shared(record.id)
        self._last_shared_at = time.time()
        return NewsHighlight(
            title=record.content,
            blurb=_draft_blurb(cognition, record),
            source=record.metadata.get("source", ""),
            topic=record.metadata.get("topic", ""),
        )


def _next_unshared(interests: InterestTracker) -> MemoryRecord | None:
    items = interests.unshared_news_items(limit=1)
    return items[0] if items else None


def _draft_blurb(cognition: CognitionRouter | None, record: MemoryRecord) -> str:
    """A genuine LLM condensation when a real provider answers; an
    honest, unembellished rendering of the raw RSS title/description
    otherwise -- never a claimed "summary" that didn't actually happen,
    the same guaranteed-floor principle as every other cognition-backed
    drafting step in this codebase.
    """
    title = record.content
    summary = record.metadata.get("summary", "") or ""
    source = record.metadata.get("source", "")
    if cognition is not None:
        try:
            response = cognition.complete(
                _HIGHLIGHT_PROMPT.format(
                    title=title, source=source, summary=summary or "(no description)"
                )
            )
            if response.provider_name != "deterministic_fallback" and response.text.strip():
                return response.text.strip()
        except ProviderUnavailable:
            pass
    return f"{title} — {summary}" if summary else title
