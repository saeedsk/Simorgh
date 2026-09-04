"""Auto-commit for applied self-modifications -- the one place in this
codebase allowed to run `git commit` on Sim's behalf.

Per the creator's explicit, logged decision (a direct answer to "why is
Sim asking for git review" -- the previous behavior was: write to disk,
then wait for the creator to run `git add`/`git commit` themselves), an
applied skill or patch that already passed `AuditGate.review()` (and, for
a self-patch, the full isolated test suite too) now also gets committed
automatically -- one commit per applied change, clearly attributed to
Simorgh rather than the creator, and NEVER pushed. `git push` remains
entirely the creator's own action; nothing in this codebase will ever run
it automatically. This is the same class of decision as removing the
human-approval gate was (docs/SOUL.md, "Self-Improvement Philosophy"),
made explicitly by the creator, not inferred.

Never skips commit hooks (no `--no-verify`) and never force-pushes or
rewrites history -- if a hook rejects the commit, that failure is
reported honestly, not bypassed; the already-applied file on disk is
untouched either way, since the write (src/orchestrator/apply.py) and the
commit here are two independent steps.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Per-command identity flags (-c user.name=/-c user.email=), not a config
# file write -- this never touches the repository's persistent git
# config, so it can't affect any other commit, including the creator's
# own. Purely so `git log` can tell an automated Sim commit apart from a
# human one at a glance.
_SIM_GIT_AUTHOR_NAME = "Simorgh"
_SIM_GIT_AUTHOR_EMAIL = "simorgh@localhost"

DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class CommitResult:
    committed: bool
    output: str


def commit_applied_change(
    repo_root: Path,
    relative_path: str,
    message: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> CommitResult:
    """Stage and commit exactly `relative_path` -- never `git add -A` or
    `-u`, only the specific file this applied change wrote, so an
    unrelated uncommitted change already sitting in the working tree is
    never swept into an automated commit.

    Never raises: a missing git binary, no repository, a rejected
    pre-commit hook, or nothing to commit (e.g. the applied content was
    byte-identical to what was already committed) all come back as
    `CommitResult(committed=False, output=...)` rather than breaking the
    apply flow that already succeeded independently of this.
    """
    run = runner or subprocess.run
    try:
        add = run(
            ["git", "add", "--", relative_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if add.returncode != 0:
            return CommitResult(False, f"git add failed: {add.stderr.strip()}")

        commit = run(
            [
                "git",
                "-c",
                f"user.name={_SIM_GIT_AUTHOR_NAME}",
                "-c",
                f"user.email={_SIM_GIT_AUTHOR_EMAIL}",
                "commit",
                "-m",
                message,
                "--",
                relative_path,
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if commit.returncode != 0:
            detail = commit.stderr.strip() or commit.stdout.strip()
            return CommitResult(False, f"git commit failed: {detail}")
        return CommitResult(True, commit.stdout.strip())
    except subprocess.TimeoutExpired:
        return CommitResult(False, f"git operation timed out after {timeout}s")
    except OSError as exc:
        return CommitResult(False, f"failed to run git: {exc!r}")
