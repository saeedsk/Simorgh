"""One worktree per task: where Sim's own edits happen, and how they land.

Until 2026-09-11 a patch task edited the live checkout -- the very tree
the running process was imported from, shared with every other task
and with the creator's own uncommitted work. Two tasks editing at once
collided; a half-written module sat under a process that might import
it; and nothing gated a commit on the whole suite, only on whatever the
model chose to run. The creator asked for the discipline every careful
contributor already follows: work on a copy, test it there, and only
then put it on main.

A git worktree is that copy. It shares the object store, costs
milliseconds, and every commit made in it is already in the same
repository, so landing is a fast-forward rather than a copy back.

    open   git worktree add -b sim/task-<id> <home>/<id> HEAD
           (or reuse the one this task already has -- a retry resumes
           where the last attempt stopped, edits and commits intact)
    work   every path tool resolves against the worktree, through
           `ToolContext.root`; scratch (`workspace/`) stays on the live
           tree so notes persist across tasks
    land   refuse a dirty tree; rebase onto main's HEAD (a conflict is
           the model's to resolve on the next attempt, never ours to
           guess at); run the gate -- the whole suite -- in a copy of
           the rebased tree; fast-forward main; remove the worktree
    close  remove the worktree and its branch, for a task that failed
           or gave up

Landing is serialised: one at a time, so two green branches cannot
both fast-forward the same main. `git merge --ff-only` refuses if the
creator's live checkout has uncommitted changes in the way, and that
refusal reaches the task as a plain reason rather than a merge nobody
asked for.

Worktrees live under the runtime data directory, never under the
repository: a checkout nested inside the tree it came from is the
mistake `tools/observer_kit.py` already guards against.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from simorgh.contracts.protocols import ToolContext, ToolResult

BRANCH_PREFIX = "sim/task-"
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")
_GIT_TIMEOUT_S = 120.0


def _git(cwd: Path, *args: str, timeout: float = _GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def _err(done: subprocess.CompletedProcess) -> str:
    return (done.stderr.strip() or done.stdout.strip())[:600]


@dataclass(frozen=True)
class Opened:
    path: Path
    head: str
    created: bool
    branch: str

    def render(self) -> str:
        """The first line is the path and the second the commit: the
        session reads both back from the tool's plain output."""
        return f"{self.path}\n{self.head}\n{'created' if self.created else 'reused'} {self.branch}"


@dataclass(frozen=True)
class Landed:
    ok: bool
    detail: str
    commit: str = ""
    landed: int = 0
    gate_output: str = ""
    conflicts: tuple[str, ...] = ()


@dataclass
class WorktreeManager:
    """Owns `<home>/<task_id>` worktrees of `repo`.

    `gate` runs the whole suite against a tree and returns a
    `ToolResult`; `None` lands without one, which is only right for a
    test of this module."""

    repo: Path
    home: Path
    gate: Callable[[Path], ToolResult] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self) -> None:
        self.repo = Path(self.repo).resolve()
        self.home = Path(self.home)

    # -- where ---------------------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return (self.repo / ".git").exists() and shutil.which("git") is not None

    @staticmethod
    def branch_for(task_id: str) -> str:
        return BRANCH_PREFIX + _SAFE_ID.sub("-", task_id)

    def path_for(self, task_id: str) -> Path:
        return self.home / _SAFE_ID.sub("-", task_id)

    def root_for(self, task_id: str | None) -> Path | None:
        """The worktree a task is working in, or None when it has none.
        A directory is only a worktree when git says so (its `.git` is
        a file pointing back into the repository)."""
        if not task_id:
            return None
        path = self.path_for(task_id)
        return path if (path / ".git").is_file() else None

    # -- open ----------------------------------------------------------------------------------

    async def open(self, task_id: str) -> Opened:
        return await asyncio.to_thread(self._open, task_id)

    def _open(self, task_id: str) -> Opened:
        if not self.available:
            raise RuntimeError(f"{self.repo} is not a git repository, or git is not installed")
        path, branch = self.path_for(task_id), self.branch_for(task_id)
        if (path / ".git").is_file():
            head = _git(path, "rev-parse", "HEAD")
            if head.returncode == 0:
                return Opened(path, head.stdout.strip(), False, branch)
            # A directory that looks like a worktree but git cannot read:
            # start over rather than work in a tree nobody can commit to.
            shutil.rmtree(path, ignore_errors=True)
        self.home.mkdir(parents=True, exist_ok=True)
        # Forget worktrees whose directories are gone, or `add` refuses
        # the branch as "already checked out" somewhere that no longer
        # exists.
        _git(self.repo, "worktree", "prune")
        exists = _git(self.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
        if exists:
            # A branch from an earlier attempt whose worktree was lost
            # (a crash mid-task, a pruned temp directory): its commits
            # are real work, so resume on it rather than from main.
            done = _git(self.repo, "worktree", "add", str(path), branch)
        else:
            done = _git(self.repo, "worktree", "add", "-b", branch, str(path), "HEAD")
        if done.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {_err(done)}")
        head = _git(path, "rev-parse", "HEAD")
        return Opened(path, head.stdout.strip() if head.returncode == 0 else "", True, branch)

    # -- land ----------------------------------------------------------------------------------

    async def land(self, task_id: str) -> Landed:
        async with self._lock:
            return await asyncio.to_thread(self._land, task_id)

    def _land(self, task_id: str) -> Landed:
        path, branch = self.path_for(task_id), self.branch_for(task_id)
        if not (path / ".git").is_file():
            return Landed(False, f"no worktree is open for task {task_id}")

        status = _git(path, "status", "--porcelain")
        if status.returncode != 0:
            return Landed(False, f"git status failed in the worktree: {_err(status)}")
        dirty = [line for line in status.stdout.splitlines() if line.strip()]
        if dirty:
            shown = ", ".join(line[3:] for line in dirty[:10]) + (" ..." if len(dirty) > 10 else "")
            return Landed(False, f"refused: the worktree has {len(dirty)} uncommitted change(s) -- "
                                 f"commit or discard them first: {shown}")

        main_head = _git(self.repo, "rev-parse", "HEAD")
        branch_head = _git(path, "rev-parse", "HEAD")
        if main_head.returncode != 0 or branch_head.returncode != 0:
            return Landed(False, f"could not read HEAD: {_err(main_head) or _err(branch_head)}")
        main_sha, branch_sha = main_head.stdout.strip(), branch_head.stdout.strip()
        if _git(self.repo, "merge-base", "--is-ancestor", branch_sha, main_sha).returncode == 0:
            self._remove(path, branch)
            return Landed(True, "nothing to land: the worktree made no commits", commit=main_sha, landed=0)

        rebase = _git(path, "-c", "user.name=Simorgh", "-c", "user.email=simorgh@localhost",
                      "rebase", main_sha)
        if rebase.returncode != 0:
            conflicts = _git(path, "diff", "--name-only", "--diff-filter=U")
            names = tuple(n for n in conflicts.stdout.split() if n)
            _git(path, "rebase", "--abort")
            return Landed(
                False,
                f"refused: rebasing onto main ({main_sha[:12]}) conflicts in "
                f"{', '.join(names) or 'an unknown file'} -- resolve against the current main "
                f"and commit again",
                conflicts=names,
            )

        if self.gate is not None:
            started = time.monotonic()
            gate = self.gate(path)
            if not gate.ok:
                tail = (gate.output or "")[-2000:]
                took = time.monotonic() - started
                if gate.error == "timeout":
                    # Not red: unfinished. Saying "red" here would send
                    # the model hunting for a failure that does not exist.
                    detail = (f"refused: the whole-suite gate did not finish within {took:.0f}s on the "
                              f"rebased tree -- nothing is known to be broken; try landing again when "
                              f"the machine is quieter")
                else:
                    detail = (f"refused: the whole suite is red on the rebased tree "
                              f"({gate.error or 'failed'}, {took:.0f}s) -- fix it and commit again")
                return Landed(False, detail, gate_output=tail)

        landed_from = _git(path, "rev-parse", "HEAD").stdout.strip()
        merge = _git(self.repo, "merge", "--ff-only", landed_from)
        if merge.returncode != 0:
            return Landed(False, f"refused: main could not fast-forward -- {_err(merge)}")
        new_main = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        count = _git(self.repo, "rev-list", "--count", f"{main_sha}..{new_main}")
        landed = int(count.stdout.strip() or 0) if count.returncode == 0 else 0
        self._remove(path, branch)
        return Landed(True, f"landed {landed} commit(s) on main: {main_sha[:12]} -> {new_main[:12]}",
                      commit=new_main, landed=landed)

    # -- close ---------------------------------------------------------------------------------

    async def close(self, task_id: str) -> str:
        return await asyncio.to_thread(self._close, task_id)

    def _close(self, task_id: str) -> str:
        path, branch = self.path_for(task_id), self.branch_for(task_id)
        if not path.exists():
            return f"no worktree for task {task_id}"
        self._remove(path, branch)
        return f"removed the worktree for task {task_id}"

    def _remove(self, path: Path, branch: str) -> None:
        done = _git(self.repo, "worktree", "remove", "--force", str(path))
        if done.returncode != 0 and path.exists():
            shutil.rmtree(path, ignore_errors=True)
            _git(self.repo, "worktree", "prune")
        _git(self.repo, "branch", "-D", branch)

    def prune(self, max_age_s: float) -> list[str]:
        """Remove worktrees nothing has touched for `max_age_s`. A task
        that is still being retried touches its tree every attempt; one
        whose task died with the process never will."""
        removed: list[str] = []
        if not self.home.is_dir():
            return removed
        now = time.time()
        for path in sorted(self.home.iterdir()):
            if not (path / ".git").is_file():
                continue
            try:
                age = now - path.stat().st_mtime
            except OSError:
                continue
            if age > max_age_s:
                self._remove(path, BRANCH_PREFIX + path.name)
                removed.append(path.name)
        return removed


# -- the tools -----------------------------------------------------------------------------------
#
# Proposed by the session runner, not by the model: none has a marker,
# so the model cannot ask for one. They still travel through Guardian
# like every other action -- Guardian sees every call, by design.


def _task_of(args: dict, ctx: ToolContext) -> str:
    return str(ctx.task_id or args.get("task_id") or "").strip()


class WorktreeOpenTool:
    name = "worktree_open"
    description = "Open (or resume) this task's own worktree of the repository, branched from HEAD."
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "properties": {"task_id": {"type": "string"}}}

    def __init__(self, manager: WorktreeManager) -> None:
        self._manager = manager

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        task_id = _task_of(args, ctx)
        if not task_id:
            return ToolResult(ok=False, error="refused: a worktree belongs to a task, and this call names none")
        try:
            opened = await self._manager.open(task_id)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            return ToolResult(ok=False, error=f"could not open a worktree: {exc}")
        return ToolResult(
            ok=True, output=opened.render(),
            metadata={"path": str(opened.path), "head": opened.head, "created": opened.created,
                      "branch": opened.branch},
        )


class WorktreeLandTool:
    name = "worktree_land"
    description = ("Land this task's worktree on main: rebase, run the whole suite, fast-forward. "
                   "Refuses a dirty tree, a conflict, or a red suite.")
    read_only = False
    reversibility = "irreversible"
    args_schema = {"type": "object", "properties": {"task_id": {"type": "string"}}}

    def __init__(self, manager: WorktreeManager, *, timeout_s: float) -> None:
        self._manager = manager
        self._timeout_s = timeout_s

    @property
    def timeout_s(self) -> float:
        """The gate is a whole-suite run; the service's default bound
        (60s) would cut it off from outside. Same shape as `RunTestsTool`."""
        return self._timeout_s

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        task_id = _task_of(args, ctx)
        if not task_id:
            return ToolResult(ok=False, error="refused: a worktree belongs to a task, and this call names none")
        try:
            landed = await self._manager.land(task_id)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            return ToolResult(ok=False, error=f"could not land: {exc}")
        metadata = {"commit": landed.commit, "landed": landed.landed, "conflicts": list(landed.conflicts)}
        if landed.gate_output:
            metadata["gate_output"] = landed.gate_output
        if not landed.ok:
            output = landed.gate_output
            return ToolResult(ok=False, error=landed.detail, output=output, metadata=metadata)
        return ToolResult(ok=True, output=landed.detail,
                          side_effects=(f"worktree_land:{landed.commit}",) if landed.landed else (),
                          metadata=metadata)


class WorktreeCloseTool:
    name = "worktree_close"
    description = "Remove this task's worktree and branch, discarding whatever was not landed."
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "properties": {"task_id": {"type": "string"}}}

    def __init__(self, manager: WorktreeManager) -> None:
        self._manager = manager

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        task_id = _task_of(args, ctx)
        if not task_id:
            return ToolResult(ok=False, error="refused: a worktree belongs to a task, and this call names none")
        try:
            detail = await self._manager.close(task_id)
        except (OSError, subprocess.SubprocessError) as exc:
            return ToolResult(ok=False, error=f"could not close the worktree: {exc}")
        return ToolResult(ok=True, output=detail)


def worktree_tools(manager: WorktreeManager, *, land_timeout_s: float) -> list:
    return [WorktreeOpenTool(manager), WorktreeLandTool(manager, timeout_s=land_timeout_s),
            WorktreeCloseTool(manager)]


__all__ = ["BRANCH_PREFIX", "Landed", "Opened", "WorktreeCloseTool", "WorktreeLandTool",
           "WorktreeManager", "WorktreeOpenTool", "worktree_tools"]
