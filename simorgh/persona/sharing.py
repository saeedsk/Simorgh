"""`SharePolicy` -- pacing/etiquette for `curiosity.share.proposed`, a
port of v1's `src/orchestrator/socializing.py` cooldowns (per-kind
cooldown, quiet period after user activity, an hourly cap across kinds).
Persona decides *whether now*; Curiosity decided *what*.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShareDecision:
    share: bool
    reason: str
    defer_until: float | None = None


class SharePolicy:
    def __init__(
        self, *, growth_cooldown_s: float = 900.0, news_cooldown_s: float = 1800.0,
        quiet_when_active_s: float = 20.0, max_per_hour: int = 4,
    ) -> None:
        self._growth_cooldown_s = growth_cooldown_s
        self._news_cooldown_s = news_cooldown_s
        self._quiet_when_active_s = quiet_when_active_s
        self._max_per_hour = max_per_hour
        self._last_share: dict[str, float] = {}
        self._share_times: list[float] = []
        self._last_user_activity: float = 0.0
        self._suspended = False

    def note_user_activity(self, now: float) -> None:
        self._last_user_activity = now

    def note_shared(self, kind: str, now: float) -> None:
        self._last_share[kind] = now
        self._share_times.append(now)

    def suspend(self, suspended: bool) -> None:
        """`system.state.changed`: suppress while paused/stopping."""
        self._suspended = suspended

    def decide(self, kind: str, now: float, *, explicit_ask: bool = False) -> ShareDecision:
        if self._suspended and not explicit_ask:
            return ShareDecision(False, "system is paused")
        if not explicit_ask and now - self._last_user_activity < self._quiet_when_active_s:
            return ShareDecision(False, "user active recently", defer_until=self._last_user_activity + self._quiet_when_active_s)
        cooldown = self._growth_cooldown_s if kind == "growth" else self._news_cooldown_s
        last = self._last_share.get(kind, 0.0)
        if not explicit_ask and now - last < cooldown:
            return ShareDecision(False, f"{kind} cooldown active", defer_until=last + cooldown)
        recent = [t for t in self._share_times if now - t < 3600.0]
        if not explicit_ask and len(recent) >= self._max_per_hour:
            return ShareDecision(False, "hourly share cap reached")
        return ShareDecision(True, "ok")
