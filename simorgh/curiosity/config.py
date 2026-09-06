"""Config for `simorgh.curiosity` (`[curiosity]` in `simorgh.toml`;
docs/blueprint/subsystems/13-curiosity.md section 3.5). Every default
below carries a v1 name in a comment so the migration is traceable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

_DEFAULT_TOPICS = (
    ("https://hnrss.org/frontpage", "technology"),
    ("http://feeds.bbci.co.uk/news/world/rss.xml", "world news"),
    ("https://www.nasa.gov/feed/", "space & science"),
)


@dataclass(frozen=True)
class Config:
    candidates_per_tick: int = 2  # v1 DEFAULT_CREATIVE_AGENDA_COUNT
    recent_subjects: int = 30  # v1 _CREATIVE_AGENDA_RECENT_SUBJECTS
    drive_gap: float = 0.45
    drive_staleness: float = 0.30
    drive_interest: float = 0.15
    drive_boredom: float = 0.10
    temperature: float = 0.7
    project_chance: float = 0.2  # v1 DEFAULT_CREATIVE_PROJECT_CHANCE
    boredom_after_seconds: float = 1800.0
    staleness_horizon_seconds: float = 7 * 86400.0
    budget_backoff_below_remaining: float = 0.2
    budget_stop_below_remaining: float = 0.05
    interest_follow_up_cooldown_seconds: float = 3600.0
    interest_max_items_per_follow_up: int = 5
    interest_default_topics: tuple[tuple[str, str], ...] = field(default_factory=lambda: _DEFAULT_TOPICS)
    share_growth_cooldown_seconds: float = 900.0
    share_news_cooldown_seconds: float = 1800.0
    mood_arousal_temperature_gain: float = 0.2
    world_query_timeout: float = 3.0
    cognition_timeout: float = 20.0
    active_project_confirm_timeout: float = 60.0
    focus: Mapping[str, float] = field(default_factory=dict)  # [curiosity.focus] area -> multiplier

    @property
    def drive_weights(self) -> dict[str, float]:
        raw = {
            "gap": self.drive_gap, "staleness": self.drive_staleness,
            "interest": self.drive_interest, "boredom": self.drive_boredom,
        }
        total = sum(raw.values()) or 1.0
        return {k: v / total for k, v in raw.items()}

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object] | None) -> "Config":
        if not mapping:
            return cls()
        m = dict(mapping)
        focus = m.pop("focus", None) or {}
        topics = m.pop("interest_default_topics", None)
        kwargs = {k: v for k, v in m.items() if k in cls.__dataclass_fields__}
        if topics is not None:
            kwargs["interest_default_topics"] = tuple(tuple(t) for t in topics)
        return cls(focus=dict(focus), **kwargs)
