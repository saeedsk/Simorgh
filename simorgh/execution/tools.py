"""Builtin tools (08-execution.md section 5.2), ported from v1. Each
implements `contracts.protocols.Tool`. Scoped this build to the tools
that don't depend on a subsystem that doesn't exist yet this phase
(Cognition for drafting loops) -- `read_file`, `list_dir`,
`run_python_sandboxed`, `apply_source_patch`, `git_commit`,
`git_revert`, `apply_skill`, `web_fetch`, and on-demand `skill:<name>`
tools (`SkillTool`, Phase 4 roadmap item 4.7 -- skill acquisition as
procedural memory). `shell`, `relaunch`, `hot_swap`, and
`isolated_test_suite` are still deferred; see README.md.

Every `subprocess.run` call here passes `stdin=subprocess.DEVNULL`
deliberately, not incidentally (live-caught, see `cognition/providers/
claude_code.py`'s own longer note on the same pattern): none of these
subprocesses ever need interactive input, but without an explicit
`stdin=`, each one inherits the parent's own stdin -- the creator's
real terminal, when `sim.sh` runs interactively. A sandboxed run that
hits its own `timeout` gets killed; if the killed child had put that
shared terminal into raw/cbreak mode, the kill skips its chance to
restore it, and the terminal stays broken for the rest of the session
with no trace of why.
"""

from __future__ import annotations

import difflib
import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

try:
    import resource
except ImportError:  # POSIX-only
    resource = None  # type: ignore[assignment]

from simorgh.contracts.envelope import Event
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


class FetchRefused(Exception):
    """No request was made (or its result is discarded): a disallowed
    scheme, a hostname that resolves to a private/internal address, a
    DNS failure, or an exhausted rate limit."""


class WebFetchTool:
    """Port of v1's `src/tools/web_fetch.py` -- the one reviewed path for
    real outbound network access (Guardian's own denylist,
    `guardian/config.py`, already refuses `urllib`/`requests`/`socket` in
    drafted code specifically so this hand-built tool is the only way in).
    Every fetch is: http/https GET only; blocked from private/loopback/
    link-local/reserved/multicast addresses after DNS resolution (SSRF
    protection); bounded in time and response size; rate-limited over a
    rolling window; identified by an honest User-Agent, never a spoofed
    browser string.

    `08-execution.md` section 5.2 lists this as `reversibility=read_only`,
    and Guardian's `ReversibilityRule` allows read-only actions
    unconditionally -- there is no independent network-scope rule yet
    (`guardian/rules.py::ScopeRule` notes the same kind of gap for task
    scope). The tool's own SSRF guard, size/rate caps, and honest logging
    are the actual safety boundary today, matching v1's own design intent
    (this module's docstring) rather than a Guardian-level escalation
    this build doesn't have.

    v1 rate-limited durably via `MemoryStore` (a rolling query over
    logged fetches, surviving restarts); this build's `ToolContext` has
    no injected memory client, so the limiter here is an in-process
    rolling window instead -- resets on restart, which is an honest,
    smaller guarantee than v1's, not a silent regression (a tool
    instance is constructed once at boot and reused for the process's
    lifetime, per `execution/service.py`'s `start()`, so the window is
    real across a session, just not across restarts)."""

    name = "web_fetch"
    description = "Fetch a URL's content over HTTP(S) GET. Read-only; SSRF-guarded; rate-limited."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}}

    def __init__(self, config: Config, *, opener=None, resolver=None) -> None:
        self._config = config
        self._opener = opener or urllib.request.urlopen
        self._resolver = resolver or socket.getaddrinfo
        self._recent_calls: deque[float] = deque()

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        url = args["url"]
        try:
            self._validate_url(url)
            self._enforce_rate_limit(ctx)
        except FetchRefused as exc:
            return ToolResult(ok=False, error=str(exc))

        request = urllib.request.Request(url, headers={"User-Agent": self._config.web_fetch_user_agent})
        try:
            with self._opener(request, timeout=self._config.web_fetch_timeout_s) as response:
                status_code = getattr(response, "status", 200)
                raw = response.read(self._config.web_fetch_max_bytes + 1)
        except Exception as exc:  # noqa: BLE001 -- any network failure becomes a ToolResult, never a crash
            return ToolResult(ok=False, error=f"fetch failed: {exc!r}")

        truncated = len(raw) > self._config.web_fetch_max_bytes
        content = raw[: self._config.web_fetch_max_bytes].decode("utf-8", errors="replace")
        return ToolResult(
            ok=True, output=content,
            metadata={
                "url": url, "status": status_code, "truncated": truncated,
                "sha256": hashlib.sha256(raw[: self._config.web_fetch_max_bytes]).hexdigest(),
                "fetched_at": ctx.clock.now(),
            },
        )

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise FetchRefused(f"refusing {url!r}: only http/https URLs are allowed")
        if not parsed.hostname:
            raise FetchRefused(f"refusing {url!r}: no hostname")
        if self._config.web_fetch_allow_private_networks:
            return
        try:
            addrinfo = self._resolver(parsed.hostname, None)
        except socket.gaierror as exc:
            raise FetchRefused(f"refusing {url!r}: could not resolve host: {exc!r}") from exc
        for entry in addrinfo:
            ip = ipaddress.ip_address(entry[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise FetchRefused(f"refusing {url!r}: resolves to a private/internal address ({ip}) -- SSRF protection")

    def _enforce_rate_limit(self, ctx: ToolContext) -> None:
        now = ctx.clock.now()
        cutoff = now - self._config.web_fetch_window_s
        while self._recent_calls and self._recent_calls[0] < cutoff:
            self._recent_calls.popleft()
        if len(self._recent_calls) >= self._config.web_fetch_max_calls:
            raise FetchRefused(
                f"rate limit exceeded: {len(self._recent_calls)}/{self._config.web_fetch_max_calls} "
                f"fetches in the last {self._config.web_fetch_window_s:.0f}s"
            )
        self._recent_calls.append(now)


MCP_PROPOSALS_STREAM = "mcp:proposals"
_PROPOSAL_ALLOWED_COMMANDS = frozenset({"npx", "uvx", "node", "python", "python3"})
_PROPOSAL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PROPOSAL_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PROPOSAL_FIELD_RE = re.compile(r"^\s*([a-zA-Z_]+)\s*:\s*(.*)$")
_PROPOSAL_KEYS = frozenset({"name", "command", "args", "read_only_tools", "env_keys", "reason"})


def _parse_mcp_proposal_text(text: str) -> dict[str, str]:
    """`key: value` lines, case-insensitive keys, lenient about a value
    (like `reason`) spanning multiple lines -- a model's own free-form
    output, not a format worth being strict about."""
    fields: dict[str, str] = {}
    key: str | None = None
    for line in text.splitlines():
        match = _PROPOSAL_FIELD_RE.match(line)
        if match and match.group(1).lower() in _PROPOSAL_KEYS:
            key = match.group(1).lower()
            fields[key] = match.group(2).strip()
        elif key is not None:
            fields[key] = (fields[key] + "\n" + line).strip()
    return fields


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class ProposeMcpServerTool:
    """Sim's own half of "propose a server, one human approval" (the
    creator, live, 2026-09-06: "I'd like sim to move fast evolve fast,
    autonomously add this kind of feature... where is the autonomy?").
    Deliberately does NOT touch `simorgh.toml` itself -- it only
    validates and records a proposal (this stream) for a human to review
    with the `mcp` CLI command (`interface/dispatch.py`), the only code
    path that ever writes the file. That split is the actual answer to
    "where is the autonomy": Sim can express intent and reasoning on its
    own, fast, with no human drafting the proposal for it -- but a new
    external subprocess with new network reach is a capability grant
    serious enough to keep outside Guardian's mode-dependent trust levels
    entirely, not just behind an `irreversible` escalation that
    `mode=trusted` could auto-allow without a human ever seeing it.

    Single-argument, marker-compatible (`orchestration/tools.py`'s own
    ceiling for tools with a genuinely structured, multi-field schema):
    the model writes one `key: value` text block instead, parsed
    leniently by `_parse_mcp_proposal_text`.
    """

    name = "propose_mcp_server"
    description = (
        "Propose adding an MCP server for a human to review (the `mcp` command). Never installs or runs "
        "anything itself. Argument is a block of `key: value` lines: name, command, args (comma-separated), "
        "read_only_tools (comma-separated), env_keys (comma-separated names only -- never values), reason."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {"type": "object", "required": ["proposal"], "properties": {"proposal": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        fields = _parse_mcp_proposal_text(args.get("proposal", ""))
        name = fields.get("name", "")
        command = fields.get("command", "")
        reason = fields.get("reason", "")
        if not _PROPOSAL_NAME_RE.match(name):
            return ToolResult(ok=False, error="invalid or missing 'name' -- lowercase letters/digits/underscore, starting with a letter")
        if command not in _PROPOSAL_ALLOWED_COMMANDS:
            return ToolResult(ok=False, error=f"'command' must be one of {sorted(_PROPOSAL_ALLOWED_COMMANDS)}, got {command!r}")
        if not reason:
            return ToolResult(ok=False, error="missing 'reason' -- explain why this server is needed")
        server_args = _split_csv(fields.get("args", ""))
        read_only_tools = _split_csv(fields.get("read_only_tools", ""))
        env_keys = _split_csv(fields.get("env_keys", ""))
        for key in env_keys:
            if not _PROPOSAL_ENV_KEY_RE.match(key):
                return ToolResult(ok=False, error=f"invalid env key name {key!r} -- UPPER_SNAKE_CASE, no values, ever")

        proposal_id = uuid.uuid4().hex[:12]
        payload = {
            "proposal_id": proposal_id, "name": name, "command": command, "args": server_args,
            "read_only_tools": read_only_tools, "env_keys": env_keys, "reason": reason, "status": "pending",
        }
        await ctx.ledger.append(MCP_PROPOSALS_STREAM, Event(
            stream=MCP_PROPOSALS_STREAM, type="proposed", ts=ctx.clock.now(),
            trace_id="", causation_id=None, payload=payload,
        ))
        return ToolResult(
            ok=True, output=f"proposal {proposal_id} recorded: {name} ({command}) -- awaiting human review via `mcp`",
            metadata={"proposal_id": proposal_id, "name": name, "reason": reason},
        )


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
                    stdin=subprocess.DEVNULL,
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


def _write_scoped_file(config: Config, subject: str, code: str, *, write_scopes: tuple[str, ...]) -> ToolResult:
    """Shared body of `apply_source_patch`/`apply_skill`: write `code` to
    `subject`, refusing anything outside `write_scopes` -- a tool-level
    scope re-check independent of Guardian's own (v1's "two boundaries,
    not one")."""
    subject = subject.replace("\\", "/")
    if ".." in Path(subject).parts or not pathsafety.in_write_scope(subject, write_scopes=write_scopes):
        return ToolResult(ok=False, error=f"refused: {subject!r} is outside the writable scope")
    target = (config.repo_root / subject).resolve()
    scope_ok = any((config.repo_root / s).resolve() in target.parents or (config.repo_root / s).resolve() == target.parent
                    for s in write_scopes)
    if not scope_ok:
        return ToolResult(ok=False, error=f"refused: {subject!r} resolves outside the writable scope")
    already_existed = target.exists()
    # Live-caught (the creator: "I'd like ... code diffs ... similar UI
    # experience as claude code cli" -- 07-post-cutover-review.md §3.11):
    # `render.diff_block()` was ported from v1 but nothing ever produced a
    # diff to show it, because nothing captured the old content before
    # overwriting -- a real patch just silently replaced a file with no
    # before/after anywhere. Read it now, before the write, so a real
    # unified diff can travel through `output` -- the existing pipe to
    # `ActionResult.stdout_preview`/`output_ref`, no contracts change --
    # instead of adding a diff-shaped field that only this one tool uses.
    old_text = ""
    if already_existed:
        try:
            old_text = target.read_text()
        except (OSError, UnicodeDecodeError):
            old_text = ""  # binary or unreadable -- diff honestly unavailable, not fabricated
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code)
    output = f"wrote {subject}"
    diff_text = ""
    if already_existed and old_text and old_text != code:
        diff_lines = list(difflib.unified_diff(
            old_text.splitlines(keepends=True), code.splitlines(keepends=True),
            fromfile=f"a/{subject}", tofile=f"b/{subject}",
        ))
        if diff_lines:
            diff_text = "".join(diff_lines)
            output += "\n\n" + diff_text
    return ToolResult(
        ok=True, output=output, side_effects=(f"file_write:{subject}",),
        metadata={"overwrote_existing": already_existed, "diff": diff_text},
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
        return _write_scoped_file(self._config, args["subject"], args["code"], write_scopes=self._config.write_scopes_source)


class ApplySkillTool:
    """Port of `use_skill`/`apply_skill` (v1 `src/agents/skills/registry.py`
    write half; 08-execution.md section 5.2): writes a drafted skill's
    complete module source to its subject path, confined to
    `write_scopes_skills` (`simorgh_skills/` by default) rather than the
    source tree -- the same scope `SkillPipeline`'s `apply_skill` action
    proposal names (learning/pipeline.py)."""

    name = "apply_skill"
    description = "Write a drafted skill's complete module source to its subject path within the skill scope."
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["subject", "code"],
        "properties": {"subject": {"type": "string"}, "code": {"type": "string"}},
    }

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        return _write_scoped_file(self._config, args["subject"], args["code"], write_scopes=self._config.write_scopes_skills)


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
        run = lambda cmd: subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )

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
        run = lambda cmd: subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )
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


_SKILL_DRIVER = """import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _skill_module as _skill
_args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
if not hasattr(_skill, "run"):
    raise SystemExit("skill module has no run() entrypoint")
_result = _skill.run(**_args)
print(_result if isinstance(_result, str) else json.dumps(_result))
"""


class SkillTool:
    """A skill loaded on demand (08-execution.md section 5.2's
    `skill:<name>` convention; Phase 4 roadmap item 4.7): the acquired
    skill module's own source, executed inside the same throwaway,
    resource-bounded subprocess sandbox `run_python_sandboxed` uses, with
    its top-level `run(**args)` invoked. The source is written to its own
    file and imported under a name other than `__main__` (`_SKILL_DRIVER`)
    so a skill's own `if __name__ == "__main__":` footer, drafted by the
    skill pipeline, never fires a second time alongside the real
    invocation. Never registered at boot -- constructed by
    `Service._load_skill` only when a `learn.skill.acquired` event names
    it, or when an approved action first references it by name, which is
    what makes this "on demand" rather than a directory scan at start()."""

    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "properties": {}, "additionalProperties": True}

    def __init__(self, config: Config, *, skill_name: str, source: str, description: str) -> None:
        self._config = config
        self.name = f"skill:{skill_name}"
        self.description = description
        self._source = source

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        timeout = min(ctx.constraints.get("timeout_s", self._config.sandbox_timeout_s), self._config.sandbox_timeout_s)
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="simorgh-skill-") as workdir:
            (Path(workdir) / "_skill_module.py").write_text(self._source)
            driver = Path(workdir) / "run_skill.py"
            driver.write_text(_SKILL_DRIVER)
            preexec = _apply_rlimits(self._config.sandbox_cpu_seconds, self._config.sandbox_memory_mb * 1024 * 1024) if resource else None
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", str(driver), json.dumps(args)], capture_output=True, text=True,
                    cwd=workdir, env={}, timeout=timeout, preexec_fn=preexec,
                    stdin=subprocess.DEVNULL,
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


def builtin_tools(config: Config) -> list:
    return [
        ReadFileTool(config), ListDirTool(config), RunPythonSandboxedTool(config),
        ApplySourcePatchTool(config), GitCommitTool(config), GitRevertTool(config),
        ApplySkillTool(config), WebFetchTool(config), ProposeMcpServerTool(),
    ]
