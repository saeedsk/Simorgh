"""`ShareScheduler`: the *decision* half of proactive sharing (v1
`src/orchestrator/socializing.py` `GrowthSocializer`/`NewsSocializer`,
cooldowns ported). Growth checked before news (spec section 5.7,
matching v1's own ordering: a direct creator complaint -- "I don't see
evidence of self-improving" -- was more pointed than "share more news").
Persona (built separately) owns *how* to phrase it; Interface owns
*when* it's actually shown; this only decides *whether* it's time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .api import ShareDecision


@dataclass
class _Buffer:
    ref: str = ""
    summary: str = ""
    at: float = 0.0


class ShareScheduler:
    def __init__(self, *, growth_cooldown_seconds: float, news_cooldown_seconds: float) -> None:
        self._growth_cooldown = growth_cooldown_seconds
        self._news_cooldown = news_cooldown_seconds
        self._last_growth_share: float | None = None
        self._last_news_share: float | None = None
        self._growth_buffer: _Buffer | None = None
        self._news_buffer: _Buffer | None = None

    def offer_growth(self, ref: str, summary: str, at: float) -> None:
        if self._growth_buffer is None or at > self._growth_buffer.at:
            self._growth_buffer = _Buffer(ref, summary, at)

    def offer_news(self, ref: str, summary: str, at: float) -> None:
        if self._news_buffer is None or at > self._news_buffer.at:
            self._news_buffer = _Buffer(ref, summary, at)

    def maybe_share(self, now: float) -> ShareDecision | None:
        growth = self._growth_buffer
        if growth is not None and (self._last_growth_share is None or now - self._last_growth_share >= self._growth_cooldown):
            self._last_growth_share = now
            self._growth_buffer = None
            return ShareDecision(kind="growth", content_ref=growth.ref, summary=growth.summary, cooldown_key="growth")
        news = self._news_buffer
        if news is not None and (self._last_news_share is None or now - self._last_news_share >= self._news_cooldown):
            self._last_news_share = now
            self._news_buffer = None
            return ShareDecision(kind="news", content_ref=news.ref, summary=news.summary, cooldown_key="news")
        return None
