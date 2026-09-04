"""Interests and world-awareness: directed attention and a seam for news.

Nature doesn't attend to everything in the environment equally --
attention is shaped by standing interests. InterestTracker gives Sim a
small, persistent, evolving set of topics it's tracking (exteroception's
"what to pay attention to" half); WorldFeed is the interface a real
news/RSS/API integration plugs into later for the "what's actually
happening" half. No networked WorldFeed is implemented here -- no
credentials exist in this environment, and this project doesn't fake
integrations it can't run or test (same reasoning as
src/cognition/provider.py). See docs/BIOMIMICRY.md, "Interests &
world-awareness."
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any

from src.memory.long_term import MemoryStore


@dataclass(frozen=True)
class Interest:
    topic: str
    why: str
    created_at: float
    last_followed_up: float | None = None


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    source: str
    published_at: float


class WorldFeed(abc.ABC):
    """Interface for pulling in information about what's happening outside
    a direct request. A real implementation (RSS, a search API, etc.) is a
    drop-in subclass; nothing else in this module depends on how items are
    actually fetched.
    """

    @abc.abstractmethod
    def fetch(self, topic: str, limit: int = 5) -> list[NewsItem]:
        raise NotImplementedError


class NullWorldFeed(WorldFeed):
    """Always available, makes no network call, always returns nothing.
    The safe default -- mirrors DeterministicFallbackProvider's role for
    cognition: a floor that can't fail, not a claim of real awareness.
    """

    def fetch(self, topic: str, limit: int = 5) -> list[NewsItem]:
        return []


class InterestTracker:
    """Persists Interests in a MemoryStore (kind="interest") and helps
    decide what to follow up on next.
    """

    KIND = "interest"

    def __init__(self, store: MemoryStore, feed: WorldFeed | None = None) -> None:
        self._store = store
        self._feed = feed or NullWorldFeed()

    def note_interest(self, topic: str, why: str) -> Interest:
        """Start (or re-note) tracking `topic`. If it's already tracked,
        this adds a new record rather than mutating the old one -- the
        full history of why an interest was noted is kept, not just the
        latest reason.
        """
        record = self._store.remember(
            self.KIND, topic, why=why, last_followed_up=None
        )
        return _interest_from_record(record)

    def list_interests(self) -> list[Interest]:
        """Every tracked interest, most recently noted/followed-up first,
        one entry per topic (the latest record for that topic wins).
        """
        by_topic: dict[str, Interest] = {}
        for record in self._store.query(kind=self.KIND):
            interest = _interest_from_record(record)
            if interest.topic not in by_topic:
                by_topic[interest.topic] = interest
        return list(by_topic.values())

    def least_recently_followed_up(self) -> Interest | None:
        """The interest most overdue for attention: never-followed-up
        interests come first (oldest `created_at` first among those), then
        the one with the oldest `last_followed_up`.
        """
        interests = self.list_interests()
        if not interests:
            return None

        never_followed = [i for i in interests if i.last_followed_up is None]
        if never_followed:
            return min(never_followed, key=lambda i: i.created_at)
        return min(interests, key=lambda i: i.last_followed_up)

    def follow_up(self, topic: str, limit: int = 5) -> list[NewsItem]:
        """Fetch updates on `topic` via the configured WorldFeed and record
        that it was followed up on just now.
        """
        items = self._feed.fetch(topic, limit=limit)
        self._store.remember(
            self.KIND,
            topic,
            why=f"followed up ({len(items)} item(s) found)",
            last_followed_up=time.time(),
        )
        return items


def _interest_from_record(record: Any) -> Interest:
    return Interest(
        topic=record.content,
        why=record.metadata.get("why", ""),
        created_at=record.created_at,
        last_followed_up=record.metadata.get("last_followed_up"),
    )
