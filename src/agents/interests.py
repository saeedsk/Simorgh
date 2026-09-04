"""Interests and world-awareness: directed attention and a seam for news.

Nature doesn't attend to everything in the environment equally --
attention is shaped by standing interests. InterestTracker gives Sim a
small, persistent, evolving set of topics it's tracking (exteroception's
"what to pay attention to" half); WorldFeed is the interface a real
news/RSS/API integration plugs into for the "what's actually happening"
half. See docs/BIOMIMICRY.md, "Interests & world-awareness."

RssWorldFeed below is a real, working implementation, added once
WebFetchTool (src/tools/web_fetch.py) existed to provide a reviewed,
SSRF-safe, rate-limited HTTP GET -- a public RSS/Atom feed needs no
credentials, so this doesn't hit the "can't run or test it here" wall
that keeps src/cognition/provider.py's LLM providers behind an API key.
It deliberately never guesses or constructs a feed URL from a topic
string (this project doesn't invent URLs on anyone's behalf, see
docs/SOUL.md) -- the topic passed to `note_interest`/`follow_up` IS the
feed URL to poll. `NullWorldFeed` remains the default when no feed is
injected, and is still what a non-URL topic effectively degrades to.
"""

from __future__ import annotations

import abc
import email.utils
import html
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

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


_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_MAX_FEED_ITEMS = 50  # a bound on how many entries we ever bother parsing out of one response


class RssWorldFeed(WorldFeed):
    """Fetches `topic` (treated as a literal feed URL, never guessed or
    constructed) via the reviewed WebFetchTool, and parses RSS 2.0 or
    Atom items out of the response with the standard library's XML
    parser -- no scraping, no third-party parsing dependency. Anything
    that isn't a real http(s) URL, a failed/refused fetch, or malformed
    XML all resolve to the same empty list NullWorldFeed always
    returns -- the same guaranteed-can't-fail floor, just backed by a
    real integration when the input is actually usable.
    """

    def __init__(self, web_fetch: Any) -> None:
        self._web_fetch = web_fetch

    def fetch(self, topic: str, limit: int = 5) -> list[NewsItem]:
        from src.tools.web_fetch import FetchRefused

        parsed = urlparse(topic)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return []

        try:
            result = self._web_fetch.fetch(topic)
        except FetchRefused:
            return []
        if result.status_code != 200:
            return []
        return _parse_feed_items(result.content, source=parsed.netloc, limit=limit)


def _parse_feed_items(xml_text: str, source: str, limit: int) -> list[NewsItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items: list[NewsItem] = []
    for entry in root.findall("./channel/item")[:_MAX_FEED_ITEMS]:  # RSS 2.0
        items.append(
            NewsItem(
                title=_strip_html(_child_text(entry, "title")),
                summary=_strip_html(_child_text(entry, "description")),
                source=source,
                published_at=_parse_feed_date(_child_text(entry, "pubDate")),
            )
        )
    if not items:
        for entry in root.findall(f"{_ATOM_NS}entry")[:_MAX_FEED_ITEMS]:  # Atom
            items.append(
                NewsItem(
                    title=_strip_html(_child_text(entry, f"{_ATOM_NS}title")),
                    summary=_strip_html(
                        _child_text(entry, f"{_ATOM_NS}summary")
                        or _child_text(entry, f"{_ATOM_NS}content")
                    ),
                    source=source,
                    published_at=_parse_feed_date(_child_text(entry, f"{_ATOM_NS}updated")),
                )
            )
    return items[:limit]


def _child_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


class _TextExtractor(HTMLParser):
    """Collects only the text data between tags -- the minimum needed to
    turn RSS/Atom markup into something readable on a terminal.
    """

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _strip_html(raw: str) -> str:
    """A light, bounded HTML-tag stripper for feed title/description
    text, which routinely embeds literal markup (a `<p>`, an
    `<a href=...>`, HTML entities) that reads as noise, not content,
    once it reaches a terminal -- caught live, a real Hacker News item
    printed its raw `<p>Article URL: <a href="...">...</a></p>` HTML
    straight to the user. Not a general-purpose sanitizer, just enough
    to make feed text readable: `HTMLParser` never raises on malformed
    markup (it degrades gracefully by design), and whitespace collapses
    to single spaces so stripped tag boundaries don't run words
    together oddly. Skips parsing entirely for the overwhelmingly common
    case of already-plain text (no `<`/`&` at all).
    """
    if "<" not in raw and "&" not in raw:
        return raw
    extractor = _TextExtractor()
    extractor.feed(raw)
    return html.unescape(" ".join(extractor.text().split()))


def _parse_feed_date(raw: str) -> float:
    """Best-effort parse of RSS's RFC 822 pubDate or Atom's ISO 8601
    updated timestamp; falls back to "now" for anything else -- this
    field is informational display data, never worth failing a whole
    fetch over.
    """
    if not raw:
        return time.time()
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        if parsed is not None:
            return parsed.timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


#: A small starting set of well-known, long-standing public feeds
#: across distinct fields, so "get news from different fields and
#: domains" produces something real on a first run without the creator
#: having to configure anything first -- seeded once (src/main.py, only
#: when nothing is tracked yet) via note_interest, never re-added on a
#: later run, so the creator can freely remove or replace any of them.
#: Best-effort, not a guarantee any of these stay live forever: a
#: dead/renamed feed just silently yields no items (RssWorldFeed's
#: existing, already-tested failure-is-empty-list behavior), never an
#: error -- add or replace via 'interest <feed url>' at any time.
DEFAULT_NEWS_TOPICS: tuple[tuple[str, str], ...] = (
    ("https://hnrss.org/frontpage", "technology"),
    ("http://feeds.bbci.co.uk/news/world/rss.xml", "world news"),
    ("https://www.nasa.gov/feed/", "space & science"),
)


class InterestTracker:
    """Persists Interests in a MemoryStore (kind="interest") and helps
    decide what to follow up on next. Also persists the actual fetched
    NewsItems (kind="news_item") as they come in -- a real, evolving
    knowledge base Sim can read back later, dedup against, and decide
    what's still unshared -- not just an ephemeral list handed back to
    whoever called follow_up() and then forgotten, which is closer to
    what this looked like before src/orchestrator/socializing.py needed
    something durable to proactively draw from.
    """

    KIND = "interest"
    NEWS_ITEM_KIND = "news_item"
    NEWS_SHARED_KIND = "news_item_shared"

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
        """Fetch updates on `topic` via the configured WorldFeed, record
        that it was followed up on just now, and persist each new item
        into the knowledge base (deduped against what's already known
        for this topic, by title) so it survives past this one call.
        """
        items = self._feed.fetch(topic, limit=limit)
        self._store.remember(
            self.KIND,
            topic,
            why=f"followed up ({len(items)} item(s) found)",
            last_followed_up=time.time(),
        )
        known_titles = {
            r.content
            for r in self._store.query(kind=self.NEWS_ITEM_KIND)
            if r.metadata.get("topic") == topic
        }
        for item in items:
            if item.title in known_titles:
                continue
            self._store.remember(
                self.NEWS_ITEM_KIND,
                item.title,
                topic=topic,
                summary=item.summary,
                source=item.source,
                published_at=item.published_at,
                fetched_at=time.time(),
            )
        return items

    def unshared_news_items(self, limit: int | None = None) -> list[Any]:
        """Knowledge-base items (most recently fetched first, per
        MemoryStore.query's own ordering) that have no matching
        `news_item_shared` record yet -- what NewsSocializer draws from.
        Returns raw MemoryRecords (id + metadata), not NewsItem, since
        the caller needs the record id to mark one shared afterward.
        """
        shared_ids = {
            r.metadata.get("news_item_id") for r in self._store.query(kind=self.NEWS_SHARED_KIND)
        }
        items = [
            r for r in self._store.query(kind=self.NEWS_ITEM_KIND) if r.id not in shared_ids
        ]
        return items[:limit] if limit is not None else items

    def mark_news_item_shared(self, record_id: str) -> None:
        """Records that a knowledge-base item was shared, without
        mutating or deleting the original record -- an additive,
        event-style marker (same shape as TaskStore folding status from
        a sequence of events) rather than requiring MemoryStore to
        support in-place updates, which it deliberately doesn't.
        """
        self._store.remember(self.NEWS_SHARED_KIND, record_id, news_item_id=record_id)


def _interest_from_record(record: Any) -> Interest:
    return Interest(
        topic=record.content,
        why=record.metadata.get("why", ""),
        created_at=record.created_at,
        last_followed_up=record.metadata.get("last_followed_up"),
    )
