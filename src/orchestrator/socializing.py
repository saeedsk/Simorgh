"""Proactive socializing: Sim surfaces something on its own, during an
idle autonomous tick, instead of only ever replying to a request -- the
direct answer to "Sim should be able to start the conversation...
instead of being reactive." Built on the same "print between blocking
input() calls" pattern src/orchestrator/reminders.py already
established works safely alongside the interactive CLI loop.

Two independent sources feed this, sharing the same shape (own pacing
cooldown, `maybe_share`/`share_next`, a drafted first-person blurb):
`NewsSocializer` (external -- InterestTracker's fetched feed items) and
`GrowthSocializer` (internal -- Sim's own applied skills/patches). The
second exists because the first shipped alone, and got called out for
it directly: "I don't see any evidence of self-improving." A real
knowledge base and proactive sharing for the outside world, built before
the same thing existed for Sim's own growth, was backwards -- the
applied-change records this draws from (kind="applied_skill"/
"applied_source_patch") already existed the whole time, in the same
MemoryStore, just never narrated.

Layered on top of (never instead of) AutonomyController's own idle/
cooldown/daily-cap/circuit-breaker gates -- everything here only ever
runs from inside an already-gated autonomous tick, or a directly-typed
command. Each socializer's own pacing cooldown means sharing something
doesn't dominate every idle tick at the expense of ordinary
self-improvement work; all of it competes for the same idle ticks, this
only decides which "wins" a given one.

Kept pacing/drafting-only and print-free by design (src/main.py owns
the actual printing) so both stay unit-testable without capturing
stdout.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.agents.interests import InterestTracker
from src.cognition.provider import CognitionRouter, ProviderUnavailable
from src.memory.long_term import MemoryRecord, MemoryStore
from src.orchestrator.apply import APPLIED_KIND, APPLIED_PATCH_KIND

# Deliberately longer than AutonomyController's own
# action_cooldown_seconds (30s default as of the "hyperscale" retune --
# see autonomy.py), so a proactive share stays an occasional, welcome
# interruption rather than something competing to win every idle tick --
# but not so long it never lands within one real session. Originally an
# hour; brought to 30 minutes, then to 6 minutes (12x action_cooldown,
# the same ratio as before) alongside AutonomyController's second,
# aggressive retune -- direct creator ask: "make the self improvement
# go at hyperscale... showing constantly progress."
DEFAULT_SHARE_COOLDOWN_SECONDS = 360.0


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


GROWTH_SHARED_KIND = "growth_highlight_shared"

# Shorter than news' default -- this is the more directly-requested
# signal ("no evidence of self-improving" was the creator's own
# complaint, more specific than "share more news"), so it's paced to
# actually land within a single active session rather than only ever
# showing up for someone who leaves the CLI running for an hour.
# Retuned alongside news' cooldown for the "hyperscale" ask: 6x
# action_cooldown (was 6x at 900s/150s, kept the same ratio at 30s).
DEFAULT_GROWTH_SHARE_COOLDOWN_SECONDS = 180.0


@dataclass(frozen=True)
class GrowthHighlight:
    subject: str
    kind: str  # "skill" or "patch"
    rationale: str
    blurb: str


_GROWTH_PROMPT = """You're Sim, about to proactively tell the person you work with about \
something you just improved about yourself -- they didn't ask right now, you're bringing \
it up because it's real progress worth mentioning. Write ONE short (1-3 sentence), warm, \
first-person message in your own voice -- what changed and why it matters to them, not a \
changelog entry. No markdown, no preamble like "Update:" -- just the message itself, as \
you'd actually say it.

What changed: {subject} (a {kind})
Why: {rationale}"""


class GrowthSocializer:
    """The mirror of NewsSocializer, pointed inward: owns the pacing and
    drafting for proactively sharing one of Sim's own recently applied
    changes (a new skill, kind="applied_skill"; a real source patch,
    kind="applied_source_patch") -- both already durably recorded by
    apply.py's own pipeline, with the actual code and rationale, the
    whole time. This is the direct, felt answer to "I don't see any
    evidence of self-improving": growth that already happened, but
    previously sat inert unless someone thought to run `pending`/`log`.
    """

    def __init__(
        self, store: MemoryStore, cooldown_seconds: float = DEFAULT_GROWTH_SHARE_COOLDOWN_SECONDS
    ) -> None:
        self._store = store
        self._cooldown_seconds = cooldown_seconds
        self._last_shared_at = 0.0

    def ready(self) -> bool:
        return time.time() - self._last_shared_at >= self._cooldown_seconds

    def maybe_share(self, cognition: CognitionRouter | None) -> GrowthHighlight | None:
        """The autonomous-tick path: only does anything if `ready()`."""
        if not self.ready():
            return None
        return self.share_next(cognition)

    def share_next(self, cognition: CognitionRouter | None) -> GrowthHighlight | None:
        """Unconditional -- no pacing check. Used by `maybe_share` and
        directly by main.py's typed `growth` command, the same way
        typing `work` bypasses AutonomyController's own idle check.
        Marks whatever it returns as shared and resets the pacing clock.
        Returns None if there's nothing applied yet, or nothing new
        since the last share.
        """
        record = self._next_unshared()
        if record is None:
            return None

        self._store.remember(GROWTH_SHARED_KIND, record.id, applied_record_id=record.id)
        self._last_shared_at = time.time()
        kind_label = "skill" if record.kind == APPLIED_KIND else "patch"
        rationale = record.metadata.get("rationale", "")
        return GrowthHighlight(
            subject=record.content,
            kind=kind_label,
            rationale=rationale,
            blurb=_draft_growth_blurb(cognition, record.content, kind_label, rationale),
        )

    def _next_unshared(self) -> MemoryRecord | None:
        shared_ids = {
            r.metadata.get("applied_record_id") for r in self._store.query(kind=GROWTH_SHARED_KIND)
        }
        candidates = self._store.query(kind=APPLIED_KIND) + self._store.query(kind=APPLIED_PATCH_KIND)
        candidates.sort(key=lambda r: r.created_at, reverse=True)
        for record in candidates:
            if record.id not in shared_ids:
                return record
        return None


def _draft_growth_blurb(
    cognition: CognitionRouter | None, subject: str, kind_label: str, rationale: str
) -> str:
    """Same guaranteed-floor principle as _draft_blurb: a real LLM
    condensation when a real provider answers, an honest, unembellished
    rendering otherwise -- never a claimed reflection that didn't
    actually happen.
    """
    if cognition is not None:
        try:
            response = cognition.complete(
                _GROWTH_PROMPT.format(
                    subject=subject, kind=kind_label, rationale=rationale or "(no rationale recorded)"
                )
            )
            if response.provider_name != "deterministic_fallback" and response.text.strip():
                return response.text.strip()
        except ProviderUnavailable:
            pass
    if rationale:
        return f"I applied a {kind_label} to {subject}: {rationale}"
    return f"I applied a {kind_label} to {subject}."
