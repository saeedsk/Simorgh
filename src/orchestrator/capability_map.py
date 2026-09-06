"""Diversified target selection for self-directed ideas -- the creator's
own fix for a real, live-observed problem: discover_creative_improvements
(main.py) asks one open-ended "think ambitiously about your whole
architecture" prompt, and a model asked that way tends to keep returning
to whatever's most salient to it, not what's actually most useful to
build next. One evening produced 10+ near-duplicate "capability
negotiation" ideas across two files -- the fuzzy-dedup fix
(_creative_agenda_already_covered) catches the literal repeats, but does
nothing about the underlying clustering; a model can propose a dozen
genuinely different-sounding ideas that are still all in the same
neighborhood.

The creator's proposed fix: stop asking the model to pick its own target.
Instead, build a capability map of the codebase itself -- level 1 is each
top-level src/ subdirectory (agents, cognition, memory, orchestrator,
sandboxing, tools: the codebase's own architecture already IS a
capability taxonomy), level 2 is the real modules inside it. Both levels
are pure filesystem listings, not LLM-generated -- free, and can never
hallucinate a target that doesn't exist or drift out of sync with the
real tree. Only level 3 (what specific idea a target deserves) costs a
model call, and it's made narrow -- "propose one improvement for THIS
file" -- rather than open-ended, after the target has already been
picked randomly, weighted away from areas the backlog is already full
of. The model never gets a chance to gravitate toward its own favorite
area, because it's never asked to choose the area at all.
"""

from __future__ import annotations

import random
from pathlib import Path

# Deliberately excluded from level 1: src/agents/skills/ is a separate,
# lighter-weight pipeline for standalone add-ons (see
# discover_creative_improvements' own long-standing exclusion of it),
# not a self-patch target in the same sense as the rest of the tree.
_EXCLUDED_AREA_PATH_PARTS = ("skills",)


def list_capability_areas(repo_root: Path) -> list[str]:
    """Level 1: every top-level directory under src/ that contains at
    least one .py file, e.g. ["agents", "cognition", "memory",
    "orchestrator", "sandboxing", "tools"]. Pure filesystem read, no
    caching -- cheap enough to recompute every time, and always exactly
    matches the real codebase, unlike a stored/generated taxonomy that
    could drift as files are added or removed.
    """
    src = repo_root / "src"
    if not src.is_dir():
        return []
    areas = []
    for entry in sorted(src.iterdir()):
        if not entry.is_dir() or entry.name in _EXCLUDED_AREA_PATH_PARTS:
            continue
        if any(entry.rglob("*.py")):
            areas.append(entry.name)
    return areas


def list_capability_modules(repo_root: Path, area: str) -> list[str]:
    """Level 2: every .py module under src/<area>/, as repo-relative
    paths, excluding src/agents/skills/ specifically even when `area` is
    "agents" (skills live under agents/ but are a different pipeline --
    same exclusion discover_creative_improvements' file listing already
    applies).
    """
    area_root = repo_root / "src" / area
    if not area_root.is_dir():
        return []
    modules = []
    for path in sorted(area_root.rglob("*.py")):
        relative = path.relative_to(repo_root)
        if any(part in _EXCLUDED_AREA_PATH_PARTS for part in relative.parts):
            continue
        modules.append(str(relative))
    return modules


def pick_diverse_target(repo_root: Path, avoid_subjects: list[str]) -> str | None:
    """Picks one module, weighted toward areas `avoid_subjects` (recent
    task subjects -- what the backlog is already full of) hasn't touched
    recently, so a creative-agenda pass exploring `count` targets in one
    tick naturally spreads across different parts of the codebase rather
    than landing on the same hot area `count` times over. Two-stage
    random pick (area, then module within it) rather than one flat pick
    across every module -- keeps a large area (e.g. many small files
    under orchestrator/) from dominating purely by module count, since
    every area gets an equal first chance regardless of how many modules
    it has.

    Returns None only if the codebase genuinely has no src/ modules at
    all (never expected in practice, but this is a pure function that
    shouldn't assume its input).
    """
    areas = list_capability_areas(repo_root)
    if not areas:
        return None

    avoided_areas = {
        Path(subject).parts[1] for subject in avoid_subjects if Path(subject).parts[:1] == ("src",) and len(Path(subject).parts) > 1
    }
    fresh_areas = [a for a in areas if a not in avoided_areas]
    candidate_areas = fresh_areas or areas
    area = random.choice(candidate_areas)

    modules = list_capability_modules(repo_root, area)
    if not modules:
        return None
    fresh_modules = [m for m in modules if m not in avoid_subjects]
    return random.choice(fresh_modules or modules)
