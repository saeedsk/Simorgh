"""Execution configuration (08-execution.md section 3.5) -- a working
subset: the knobs the tools built this phase actually read. Web fetch,
shell, relaunch, hot_swap, isolated_test_suite, and skill tools (and
their config keys) are deferred -- see simorgh/execution/README.md.
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
    readable_roots: tuple[str, ...] = ("src", "docs", "tests", "simorgh")
    write_scopes_source: tuple[str, ...] = ("src/", "simorgh/")
    sandbox_cpu_seconds: int = 5
    sandbox_memory_mb: int = 256
    sandbox_timeout_s: float = 10.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "Config":
        if not data:
            return cls()
        kwargs = dict(data)
        if "repo_root" in kwargs:
            kwargs["repo_root"] = Path(kwargs["repo_root"])
        for key in ("readable_roots", "write_scopes_source"):
            if key in kwargs:
                kwargs[key] = tuple(kwargs[key])
        kwargs = {k: v for k, v in kwargs.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)
