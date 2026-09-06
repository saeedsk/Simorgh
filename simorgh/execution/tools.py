"""Builtin tools (08-execution.md section 5.2), ported from v1. Each
implements `contracts.protocols.Tool`. Scoped this build to the tools
that don't depend on a subsystem that doesn't exist yet this phase
(Cognition for drafting loops, Learning for skills) -- `read_file`,
`list_dir`, `run_python_sandboxed`, `apply_source_patch`, `git_commit`,
`git_revert`. `web_fetch`, `shell`, `relaunch`, `hot_swap`,
`isolated_test_suite`, and skill tools are deferred; see README.md.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import resource
except ImportError:  # POSIX-only
    resource = None  # type: ignore[assignment]

from simorgh.contracts.protocols import ToolContext, ToolResult

from . import pathsafety
from .config import Config


class ReadFileTool:
    name = "read_file"
    description = "Read a file's contents (path-safety bounded)."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        content = pathsafety.safe_read_file(self._config.repo_root, args["path"], readable_roots=self._config.readable_roots)
        ok = not content.startswith("[refused:")
        return ToolResult(ok=ok, output=content, error=None if ok else content)


class ListDirTool:
    name = "list_dir"
    description = "List a directory's immediate entries (path-safety bounded)."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        content = pathsafety.safe_list_dir(self._config.repo_root, args.get("path", ""), readable_roots=self._config.readable_roots)
        ok = not content.startswith("[refused:")
        return ToolResult(ok=ok, output=content, error=None if ok else content)


def _apply_rlimits(cpu_seconds: int, memory_bytes: int):
    def _set() -> None:
        for res, value in (
            (getattr(resource, "RLIMIT_CPU", None), cpu_seconds),
            (getattr(resource, "RLIMIT_AS", None), memory_bytes),
            (getattr(resource, "RLIMIT_CORE", None), 0),
        ):
            if res is None:
                continue
            try:
                resource.setrlimit(res, (value, value))
            except (ValueError, OSError):
                pass
    return _set


class RunPythonSandboxedTool:
    """Port of src/sandboxing/sandbox.py's SubprocessSandbox: a fresh
    throwaway `python -I` subprocess, empty env, temp cwd, CPU/mem/time
    limits -- deliberately no repo access (milestone 84: this isolation
    is correct for standalone code, structurally wrong for a self-patch's
    normal cross-module imports, which is why self-patches are verified
    by the isolated test suite instead, not this tool)."""

    name = "run_python_sandboxed"
    description = "Run Python code in an isolated, resource-bounded subprocess with no repo access."
    read_only = True
    reversibility = "reversible"
    args_schema = {"type": "object", "required": ["code"], "properties": {"code": {"type": "string"}}}

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        code = args["code"]
        timeout = min(ctx.constraints.get("timeout_s", self._config.sandbox_timeout_s), self._config.sandbox_timeout_s)
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="simorgh-sandbox-") as workdir:
            script = Path(workdir) / "code.py"
            script.write_text(code)
            preexec = _apply_rlimits(self._config.sandbox_cpu_seconds, self._config.sandbox_memory_mb * 1024 * 1024) if resource else None
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", str(script)], capture_output=True, text=True,
                    cwd=workdir, env={}, timeout=timeout, preexec_fn=preexec,
                )
            except subprocess.TimeoutExpired as exc:
                return ToolResult(
                    ok=False, output=(exc.stdout or ""), error="timeout",
                    metadata={"stderr": exc.stderr or "", "duration_s": time.monotonic() - start},
                )
            ok = completed.returncode == 0
            return ToolResult(
                ok=ok, output=completed.stdout,
                error=None if ok else f"exit_code={completed.returncode}",
                metadata={"stderr": completed.stderr, "exit_code": completed.returncode,
                          "duration_s": time.monotonic() - start},
            )


class ApplySourcePatchTool:
    """Port of src/orchestrator/apply.py's apply_source_patch: writes
    `args['code']` to `args['subject']`, tool-level scope re-check
    independent of Guardian's own (v1's "two boundaries, not one")."""

    name = "apply_source_patch"
    description = "Write a self-patch's complete new file content to its subject path."
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["subject", "code"],
        "properties": {"subject": {"type": "string"}, "code": {"type": "string"}},
    }

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        subject = args["subject"].replace("\\", "/")
        if ".." in Path(subject).parts or not pathsafety.in_write_scope(subject, write_scopes=self._config.write_scopes_source):
            return ToolResult(ok=False, error=f"refused: {subject!r} is outside the writable scope")
        target = (self._config.repo_root / subject).resolve()
        scope_ok = any((self._config.repo_root / s).resolve() in target.parents or (self._config.repo_root / s).resolve() == target.parent
                        for s in self._config.write_scopes_source)
        if not scope_ok:
            return ToolResult(ok=False, error=f"refused: {subject!r} resolves outside the writable scope")
        already_existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args["code"])
        return ToolResult(
            ok=True, output=f"wrote {subject}", side_effects=(f"file_write:{subject}",),
            metadata={"overwrote_existing": already_existed},
        )


_SIM_GIT_AUTHOR_NAME = "Simorgh"
_SIM_GIT_AUTHOR_EMAIL = "simorgh@localhost"


class GitCommitTool:
    """Port of src/orchestrator/git_ops.py's commit_applied_change, plus
    the milestone-93 pre-check (08-execution.md section 5.2 / S4): a
    `git diff --quiet` before committing turns v1's silently-ambiguous
    "nothing to commit" into an explicit, evidenced result instead of a
    buried edge case in the commit's own stderr. Never pushes."""

    name = "git_commit"
    description = "Stage and commit exactly one path, attributed to Simorgh. Never pushes."
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["path", "message"],
        "properties": {"path": {"type": "string"}, "message": {"type": "string"}},
    }

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        path, message = args["path"], args["message"]
        root = self._config.repo_root
        run = lambda cmd: subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=30)

        # `git diff --quiet HEAD` alone misses brand-new untracked files
        # (they're outside what `diff` compares against HEAD at all), so
        # the pre-check uses `status --porcelain` instead, which reports
        # untracked/staged/unstaged changes uniformly.
        status = run(["git", "status", "--porcelain", "--", path])
        head = run(["git", "rev-parse", "HEAD"])
        head_sha = head.stdout.strip() if head.returncode == 0 else ""
        if not status.stdout.strip():
            path_sha = run(["git", "hash-object", str(root / path)])
            return ToolResult(
                ok=False, error="nothing_to_commit",
                metadata={"head_sha": head_sha, "path_sha": path_sha.stdout.strip() if path_sha.returncode == 0 else ""},
            )

        add = run(["git", "add", "--", path])
        if add.returncode != 0:
            return ToolResult(ok=False, error=f"git add failed: {add.stderr.strip()}")
        commit = run([
            "git", "-c", f"user.name={_SIM_GIT_AUTHOR_NAME}", "-c", f"user.email={_SIM_GIT_AUTHOR_EMAIL}",
            "commit", "-m", message, "--", path,
        ])
        if commit.returncode != 0:
            detail = commit.stderr.strip() or commit.stdout.strip()
            return ToolResult(ok=False, error=f"git commit failed: {detail}")
        new_head = run(["git", "rev-parse", "HEAD"])
        return ToolResult(
            ok=True, output=commit.stdout.strip(), side_effects=(f"git_commit:{path}",),
            metadata={"commit": new_head.stdout.strip() if new_head.returncode == 0 else ""},
        )


class GitRevertTool:
    """Port of revert_last_commit: `git revert --no-edit HEAD`,
    attributed to Simorgh, never rewrites history."""

    name = "git_revert"
    description = "Revert the most recent commit as a new commit. Never rewrites history."
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "properties": {}}

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        root = self._config.repo_root
        run = lambda cmd: subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=30)
        result = run([
            "git", "-c", f"user.name={_SIM_GIT_AUTHOR_NAME}", "-c", f"user.email={_SIM_GIT_AUTHOR_EMAIL}",
            "revert", "--no-edit", "HEAD",
        ])
        if result.returncode != 0:
            return ToolResult(ok=False, error=f"git revert failed: {result.stderr.strip() or result.stdout.strip()}")
        new_head = run(["git", "rev-parse", "HEAD"])
        return ToolResult(
            ok=True, output=result.stdout.strip(), side_effects=("git_revert",),
            metadata={"commit": new_head.stdout.strip() if new_head.returncode == 0 else ""},
        )


def builtin_tools(config: Config) -> list:
    return [
        ReadFileTool(config), ListDirTool(config), RunPythonSandboxedTool(config),
        ApplySourcePatchTool(config), GitCommitTool(config), GitRevertTool(config),
    ]
