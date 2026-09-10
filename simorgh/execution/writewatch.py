"""What a command actually wrote, discovered rather than declared.

`apply_source_patch` and `apply_skill` know the path they touched and
say so, and `orchestration/session.py` turns that into `session.wrote`
-- the list every file-reading verification check works from
(`verification/checks/_files.py`).

`run_shell` and `run_script` write files too, and knew nothing about
it. `run_shell` reported `side_effects=("run_shell:<command>",)`; the
script tool reported none at all. So a task that wrote its page with a
heredoc instead of `apply_source_patch` produced an empty
`written_paths`, and `js_syntax`, `render` and `trailing_narration` all
reported "skipped" -- the checks were built the same day and were
silently inert for exactly the tasks most likely to need them. Found by
wave-21 observer W21-03, who proved it against a real bus rather than
by reading.

The trick is that git already tracks this. Snapshot `git status
--porcelain` before and after; anything whose status changed is
something the command wrote. That covers a heredoc, a `>` redirect, a
`cp`, a script writing through pandas -- every route, without the tool
having to understand any of them.

Never fatal and never guessed at: outside a git repository, or if git
fails for any reason, this reports nothing and the caller behaves
exactly as it did before. An empty answer means "I could not tell",
which is why the checks that consume it skip rather than fail.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_TIMEOUT_S = 15.0
# A command that rewrites half the tree is not telling us about one
# artifact; it is doing something else, and listing it all would bury
# the signal in the verification subject.
_MAX_REPORTED = 40


def snapshot(repo_root: Path) -> dict[str, str] | None:
    """`{path: status}` for everything git considers dirty, or None when
    git cannot answer."""
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(repo_root), capture_output=True, text=True,
            timeout=_TIMEOUT_S, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    entries: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip()
        # A rename reads `R  old -> new`; the new name is what was written.
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        entries[path] = status
    return entries


def written_between(before: dict[str, str] | None, after: dict[str, str] | None) -> list[str]:
    """Paths that appeared, or whose git status changed, between the two
    snapshots. Sorted, capped, and empty whenever either side is None."""
    if before is None or after is None:
        return []
    changed = [path for path, status in after.items() if before.get(path) != status]
    return sorted(changed)[:_MAX_REPORTED]


def side_effects_for(paths: list[str], before: dict[str, str] | None,
                     after: dict[str, str] | None = None) -> tuple[str, ...]:
    """`file_create:`/`file_write:` entries in the shape
    `session.py::_propose_and_await` already parses, so a command's
    writes are recorded exactly as a patch tool's are -- including in
    `session.uncommitted`, so the cleanup that stops a broken change
    being left in the tree covers these too.

    Which of the two matters more than it looks. `file_create` tells the
    session the file did not exist before, and cleanup DELETES a created
    file outright (`git_discard` cannot restore an untracked path). Get
    it wrong for an edit to a tracked file and cleanup destroys the
    original instead of reverting it.

    So the answer comes from git's own status letter, not from "was this
    path in the previous snapshot" -- a clean tracked file is absent
    from `git status --porcelain` entirely, so absence means "clean",
    never "did not exist". That first version would have deleted
    exactly the files it was meant to protect; its own test caught it.
    """
    after = after if after is not None else {}
    fallback = before or {}
    out = []
    for path in paths:
        status = (after.get(path) or "").strip()
        created = status.startswith("?") or status.startswith("A") or (
            not status and path not in fallback
        )
        out.append(f"{'file_create' if created else 'file_write'}:{path}")
    return tuple(out)
