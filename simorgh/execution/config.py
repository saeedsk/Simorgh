"""Execution configuration (08-execution.md section 3.5) -- a working
subset: the knobs the tools built this phase actually read. Shell,
relaunch, hot_swap, and isolated_test_suite (and their config keys) are
still deferred -- see simorgh/execution/README.md. Skill tools
(`apply_skill`, `SkillTool`, on-demand `learn.skill.acquired`
loading -- Phase 4 roadmap item 4.7) and `web_fetch` are built this pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Config:
    max_concurrent_actions: int = 4
    default_timeout_s: float = 60.0
    max_output_bytes: int = 65536
    blob_inline_threshold_bytes: int = 4096
    approval_max_age_s: float = 120.0
    repo_root: Path = field(default_factory=Path.cwd)
    readable_roots: tuple[str, ...] = ("src", "docs", "tests", "simorgh", "simorgh_skills")
    write_scopes_source: tuple[str, ...] = ("src/", "simorgh/")
    sandbox_cpu_seconds: int = 5
    sandbox_memory_mb: int = 256
    sandbox_timeout_s: float = 10.0
    # -- skills (11-learning.md's `skill_dir`; 08-execution.md's
    # `write_scopes.skills`) -- where `apply_skill` writes and
    # `learn.skill.acquired`/on-demand loading reads back from.
    skill_dir: str = "simorgh_skills"
    write_scopes_skills: tuple[str, ...] = ("simorgh_skills/",)
    skill_lookup_timeout_s: float = 2.0
    # -- web_fetch (08-execution.md section 5.2/3.5; the one reviewed path
    # for real outbound network access -- see WebFetchTool's own docstring)
    web_fetch_timeout_s: float = 10.0
    web_fetch_max_bytes: int = 200_000
    web_fetch_max_calls: int = 30
    web_fetch_window_s: float = 3600.0
    web_fetch_allow_private_networks: bool = False
    web_fetch_user_agent: str = "Simorgh/2.0 (personal AI assistant; +https://github.com/saeedsk/Simorgh)"

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "Config":
        if not data:
            return cls()
        kwargs = dict(data)
        if "repo_root" in kwargs:
            kwargs["repo_root"] = Path(kwargs["repo_root"])
        for key in ("readable_roots", "write_scopes_source", "write_scopes_skills"):
            if key in kwargs:
                kwargs[key] = tuple(kwargs[key])
        kwargs = {k: v for k, v in kwargs.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)
