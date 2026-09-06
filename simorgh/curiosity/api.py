"""Data shapes and protocols internal to `simorgh.curiosity` (docs/blueprint/
subsystems/13-curiosity.md section 3.4). Nothing here is on the wire --
wire shapes are `simorgh.contracts.messages.curiosity`; these are the
package's own working types.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol


@dataclass(frozen=True)
class Area:
    name: str
    modules: tuple[str, ...]


@dataclass(frozen=True)
class Gap:
    competence: str
    task_type: str
    score: float
    samples: int


@dataclass(frozen=True)
class Target:
    area: str
    subject: str  # a repo-relative module path


@dataclass(frozen=True)
class Idea:
    kind: str  # "patch" | "research"
    description: str


@dataclass(frozen=True)
class DriveContext:
    areas: tuple[Area, ...]
    gaps: tuple[Gap, ...]
    interests: tuple[str, ...]  # lowercased topic words, for lexical matching
    boredom: float  # already computed in [0, 1]
    staleness_by_area: dict  # area -> seconds since last touched (float | None)
    staleness_horizon: float


# `ThinkFn(purpose, prompt, *, expected=None) -> (text, floor, provider_name)` --
# a thin async wrapper `service.py` builds around `cognition.think` so the
# proposer classes below never touch the bus directly (easy to fake in tests).
ThinkFn = Callable[..., Awaitable[tuple[str, bool, str]]]


class TargetSampler(Protocol):
    def pick(
        self, ctx: DriveContext, recent_subjects: list[str], *, rng: random.Random, temperature: float
    ) -> Target | None: ...


class IdeaProposer(Protocol):
    async def propose(self, target: Target, content_preview: str, think: ThinkFn) -> Idea | None: ...


class ProjectProposer(Protocol):
    async def propose(self, files: list[str], think: ThinkFn) -> str | None: ...


@dataclass(frozen=True)
class Interest:
    topic: str
    why: str
    created_at: float
    last_followed_up: float | None = None
    score: float = 1.0


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    source: str
    published_at: float


@dataclass(frozen=True)
class ShareDecision:
    kind: str  # "growth" | "news"
    content_ref: str
    summary: str
    cooldown_key: str
