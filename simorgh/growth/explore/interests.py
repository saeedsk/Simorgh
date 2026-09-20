"""`InterestService` (v1 `src/agents/interests.py` `InterestTracker`,
ported) plus the RSS/Atom feed parser (v1 `RssWorldFeed._parse_feed_items`
et al., ported near-verbatim -- pure stdlib XML parsing, no v2-specific
change needed). Deliberately never guesses or constructs a feed URL from
a topic string (v1 lesson, `docs/SOUL.md`) -- the topic IS the feed URL
to poll, or a plain label with no feed. Fetching itself is never a direct
network call here: `service.py` proposes a `web_fetch` action through
Guardian; this module only tracks state and parses whatever `action.result`
brings back.
"""

from __future__ import annotations

import email.utils
import html
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlparse

from .api import Interest, NewsItem

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_MAX_FEED_ITEMS = 50


def is_feed_url(topic: str) -> bool:
    parsed = urlparse(topic)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def parse_feed_items(xml_text: str, *, source: str, limit: int) -> list[NewsItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items: list[NewsItem] = []
    for entry in root.findall("./channel/item")[:_MAX_FEED_ITEMS]:
        items.append(NewsItem(
            title=_strip_html(_child_text(entry, "title")),
            summary=_strip_html(_child_text(entry, "description")),
            source=source,
            published_at=_parse_feed_date(_child_text(entry, "pubDate")),
        ))
    if not items:
        for entry in root.findall(f"{_ATOM_NS}entry")[:_MAX_FEED_ITEMS]:
            items.append(NewsItem(
                title=_strip_html(_child_text(entry, f"{_ATOM_NS}title")),
                summary=_strip_html(_child_text(entry, f"{_ATOM_NS}summary") or _child_text(entry, f"{_ATOM_NS}content")),
                source=source,
                published_at=_parse_feed_date(_child_text(entry, f"{_ATOM_NS}updated")),
            ))
    return items[:limit]


def _child_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _strip_html(raw: str) -> str:
    if "<" not in raw and "&" not in raw:
        return raw
    extractor = _TextExtractor()
    extractor.feed(raw)
    return html.unescape(" ".join(extractor.text().split()))


def _parse_feed_date(raw: str) -> float:
    if not raw:
        return time.time()
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        if parsed is not None:
            return parsed.timestamp()
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime

        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


class InterestService:
    """Pure in-memory state (rebuilt by `service.py` from the
    `curiosity:interests` Ledger stream at `start()`); no bus/ledger I/O
    of its own, matching `api.InterestTracker`'s protocol shape exactly
    so it is trivially fakeable in tests."""

    def __init__(self, *, follow_up_cooldown_seconds: float, decay_rate_per_day: float = 0.02) -> None:
        self._cooldown = follow_up_cooldown_seconds
        self._decay_rate = decay_rate_per_day
        self._by_topic: dict[str, Interest] = {}

    def note(self, topic: str, why: str = "noted") -> Interest:
        existing = self._by_topic.get(topic)
        interest = Interest(
            topic=topic, why=why, created_at=existing.created_at if existing else time.time(),
            last_followed_up=existing.last_followed_up if existing else None,
            score=existing.score if existing else 1.0,
        )
        self._by_topic[topic] = interest
        return interest

    def list_interests(self) -> list[Interest]:
        return list(self._by_topic.values())

    def least_recently_followed(self, *, now: float) -> Interest | None:
        candidates = [
            i for i in self._by_topic.values()
            if i.last_followed_up is None or (now - i.last_followed_up) >= self._cooldown
        ]
        if not candidates:
            return None
        never = [i for i in candidates if i.last_followed_up is None]
        if never:
            return min(never, key=lambda i: i.created_at)
        return min(candidates, key=lambda i: i.last_followed_up)

    def record_follow_up(self, topic: str, items: list[NewsItem], *, now: float, denied: bool = False) -> Interest:
        existing = self._by_topic.get(topic)
        score = existing.score if existing else 1.0
        if denied or not items:
            score = max(0.0, score - 0.2)  # decays faster when it can't be pursued (spec S5)
        interest = Interest(
            topic=topic, why=f"followed up ({len(items)} item(s) found)",
            created_at=existing.created_at if existing else now, last_followed_up=now, score=score,
        )
        self._by_topic[topic] = interest
        return interest

    def decay(self, now: float, *, elapsed_days: float) -> None:
        rate = self._decay_rate * elapsed_days
        for topic, interest in list(self._by_topic.items()):
            self._by_topic[topic] = Interest(
                topic=interest.topic, why=interest.why, created_at=interest.created_at,
                last_followed_up=interest.last_followed_up, score=max(0.0, interest.score - rate),
            )

    def topics_lower(self) -> tuple[str, ...]:
        return tuple(i.topic.lower() for i in self._by_topic.values())
