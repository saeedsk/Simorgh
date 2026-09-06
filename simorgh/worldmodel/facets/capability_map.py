"""Level 1/2 of the capability map -- a direct port of v1's
`src/orchestrator/capability_map.py` (`list_capability_areas`,
`list_capability_modules`). Pure filesystem listings, no LLM: the
codebase's own directory structure already is a capability taxonomy, so
this can never hallucinate a target or drift from the real tree. The
random *choice* half of v1's `pick_diverse_target` moves to Curiosity
(Phase 3, docs/blueprint/subsystems/13-curiosity.md); this facet is the
*inventory* Curiosity's sampler will read via `world.env.query`.
"""

from __future__ import annotations

from pathlib import Path

EXCLUDED_AREA_PATH_PARTS = ("skills",)


def list_capability_areas(repo_root: Path) -> list[str]:
    src = repo_root / "src"
    if not src.is_dir():
        return []
    areas = []
    for entry in sorted(src.iterdir()):
        if not entry.is_dir() or entry.name in EXCLUDED_AREA_PATH_PARTS:
            continue
        if any(entry.rglob("*.py")):
            areas.append(entry.name)
    return areas


def list_capability_modules(repo_root: Path, area: str) -> list[str]:
    area_root = repo_root / "src" / area
    if not area_root.is_dir():
        return []
    modules = []
    for path in sorted(area_root.rglob("*.py")):
        relative = path.relative_to(repo_root)
        if any(part in EXCLUDED_AREA_PATH_PARTS for part in relative.parts):
            continue
        modules.append(str(relative))
    return modules


class CapabilityMapFacet:
    """`Facet` protocol conformance (api.py) over the two functions above,
    plus `coverage()` -- a stub this session (empty dict): joining with
    `world:coverage` (task events) is Phase 2+, once Planning exists to
    emit `task.created`/`.completed` in the first place. `get()` never
    raises on a missing/unreadable repo_root -- returns an honest empty
    inventory (S4 in the spec: a degraded floor, not a crash).
    """

    name = "capability_map"

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def areas(self) -> list[str]:
        return list_capability_areas(self._repo_root)

    def modules(self, area: str) -> list[str]:
        return list_capability_modules(self._repo_root, area)

    def coverage(self) -> dict:
        return {}

    async def get(self, args: dict) -> dict:
        areas = self.areas()
        if "area" in (args or {}):
            return {"area": args["area"], "modules": self.modules(args["area"])}
        return {"areas": areas, "modules_by_area": {a: self.modules(a) for a in areas}}

    def invalidate(self) -> None:
        pass  # nothing cached -- always a fresh filesystem read (matches v1's own reasoning)
