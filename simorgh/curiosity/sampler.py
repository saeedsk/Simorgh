"""`TargetSampler`: the upgraded `pick_diverse_target` (v1
`src/orchestrator/capability_map.py`) -- two-stage random pick (area,
then module), now weighted by `DriveEngine` scores via softmax rather
than plain avoid-list + uniform. Softmax, never argmax: greedy selection
on drive scores fixates on the single weakest area until it improves,
which is a slower, one-dimensional version of the exact thematic
collapse this whole subsystem exists to prevent (spec section 7).
Temperature is a real knob: T -> 0 approaches greedy, T -> inf approaches
uniform -- mood modulates it, never replaces it.
"""

from __future__ import annotations

import math
import random

from .api import Area, DriveContext, Target
from .drives import DriveEngine


def softmax_sample(scores: dict[str, float], *, rng: random.Random, temperature: float) -> str:
    """Pick a key from `scores` with softmax probability at `temperature`.
    `temperature` clamped to a small positive floor so a caller passing 0
    degrades to (near-)greedy rather than raising a division error."""
    names = list(scores)
    temperature = max(temperature, 1e-6)
    values = [scores[n] / temperature for n in names]
    top = max(values)
    weights = [math.exp(v - top) for v in values]  # shift for numerical stability
    total = sum(weights)
    probs = [w / total for w in weights]
    r = rng.random()
    cumulative = 0.0
    for name, p in zip(names, probs):
        cumulative += p
        if r <= cumulative:
            return name
    return names[-1]


class DriveWeightedSampler:
    """The real `TargetSampler` (spec section 5.2)."""

    def __init__(self, engine: DriveEngine) -> None:
        self._engine = engine

    def pick(
        self, ctx: DriveContext, recent_subjects: list[str], *, rng: random.Random, temperature: float
    ) -> Target | None:
        if not ctx.areas:
            return None
        # Area selection is itself restricted to areas that still have an
        # unvisited module, whenever any exist -- otherwise a run with two
        # equally-scored areas could keep re-sampling one of them by pure
        # softmax luck while the other's modules sit untouched, which is
        # exactly the collapse this whole sampler exists to prevent (spec
        # section 7). Only once every area is fully recent does the whole
        # map become eligible again, i.e. a fresh lap.
        with_fresh = [a for a in ctx.areas if a.modules and any(m not in recent_subjects for m in a.modules)]
        candidate_areas = with_fresh or [a for a in ctx.areas if a.modules]
        if not candidate_areas:
            return None
        scores = {a.name: self._engine.score_area(a.name, ctx)["total"] for a in candidate_areas}
        area_name = softmax_sample(scores, rng=rng, temperature=temperature)
        area = next(a for a in candidate_areas if a.name == area_name)
        fresh = [m for m in area.modules if m not in recent_subjects]
        modules = fresh or list(area.modules)
        subject = rng.choice(modules)
        return Target(area=area_name, subject=subject)

    def score_table(self, ctx: DriveContext) -> dict[str, dict[str, float]]:
        """The full per-area breakdown, for the `curiosity:ticks` audit
        record (spec section 5.2: "every pick, with the full score
        table, is appended")."""
        return {a.name: self._engine.score_area(a.name, ctx) for a in ctx.areas}
