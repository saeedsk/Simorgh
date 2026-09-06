"""`DriveEngine`: per-area scores from four drives (spec section 5.1).
Unknown-area gap defaults to 0.6, not 0 -- an area nothing has ever been
measured on is not evidence of competence, it's evidence of ignorance,
and treating it as "fine" would mean Curiosity never explores anything
new. Boredom is added uniformly (it flattens the distribution -- when
bored, wander -- rather than picking a direction).
"""

from __future__ import annotations

from dataclasses import dataclass

from .api import DriveContext
from .config import Config

_UNKNOWN_AREA_GAP = 0.6


@dataclass(frozen=True)
class DriveEngine:
    config: Config

    def score_area(self, area_name: str, ctx: DriveContext, focus_multiplier: float = 1.0) -> dict[str, float]:
        weights = self.config.drive_weights
        gap = self._gap(area_name, ctx)
        staleness = self._staleness(area_name, ctx)
        interest = self._interest(area_name, ctx)
        boredom = ctx.boredom
        total = (
            weights["gap"] * gap
            + weights["staleness"] * staleness
            + weights["interest"] * interest
            + weights["boredom"] * boredom
        ) * focus_multiplier
        return {"gap": gap, "staleness": staleness, "interest": interest, "boredom": boredom, "total": total}

    def _gap(self, area_name: str, ctx: DriveContext) -> float:
        matches = [g for g in ctx.gaps if g.competence == area_name or g.task_type.startswith(area_name)]
        if not matches:
            return _UNKNOWN_AREA_GAP
        # confidence-weighted: more samples -> trust the measured gap more; few samples pull toward "unknown"
        weighted, weight_sum = 0.0, 0.0
        for g in matches:
            confidence = min(1.0, g.samples / 8.0)
            gap_value = max(0.0, 1.0 - g.score)
            blended = confidence * gap_value + (1 - confidence) * _UNKNOWN_AREA_GAP
            weighted += blended
            weight_sum += 1.0
        return weighted / weight_sum if weight_sum else _UNKNOWN_AREA_GAP

    def _staleness(self, area_name: str, ctx: DriveContext) -> float:
        age = ctx.staleness_by_area.get(area_name)
        if age is None:
            return 1.0  # never touched at all -- maximally stale
        horizon = ctx.staleness_horizon or self.config.staleness_horizon_seconds
        return min(1.0, max(0.0, age / horizon)) if horizon > 0 else 0.0

    def _interest(self, area_name: str, ctx: DriveContext) -> float:
        if not ctx.interests:
            return 0.0
        name = area_name.lower()
        best = 0.0
        for topic in ctx.interests:
            if name in topic or any(word == name for word in topic.split()):
                best = max(best, 1.0)
        return best

    def temperature(self, arousal: float) -> float:
        gain = self.config.mood_arousal_temperature_gain
        return self.config.temperature + gain * max(0.0, arousal)

    def research_prior_multiplier(self, valence: float) -> float:
        return 1.5 if valence < -0.4 else 1.0
