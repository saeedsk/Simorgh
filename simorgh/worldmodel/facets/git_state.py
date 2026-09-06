"""`git_state` facet -- read-only `git` observation via a subprocess run
in a thread (never blocks the event loop). Degrades honestly
(`available: false`) when `git` is missing or the tree isn't a repo (S4
in the spec) rather than raising -- a host without git is a real,
expected condition, not an error.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path


class GitStateFacet:
    name = "git_state"

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def invalidate(self) -> None:
        pass  # the caller (service.py) re-polls on its own refresh_seconds cadence

    async def get(self, args: dict) -> dict:
        return await asyncio.to_thread(self._read)

    def _read(self) -> dict:
        def run(*args: str) -> str | None:
            try:
                result = subprocess.run(
                    ["git", *args], cwd=self._repo_root, capture_output=True, text=True, timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            return result.stdout.strip() if result.returncode == 0 else None

        branch = run("rev-parse", "--abbrev-ref", "HEAD")
        if branch is None:
            return {"available": False}
        head = run("rev-parse", "HEAD") or ""
        status = run("status", "--porcelain") or ""
        log = run("log", "-5", "--oneline") or ""
        return {
            "available": True,
            "branch": branch,
            "head": head,
            "dirty": bool(status.strip()),
            "changed_files": len([l for l in status.splitlines() if l.strip()]),
            "recent_commits": log.splitlines(),
        }
