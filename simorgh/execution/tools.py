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

import ast

import difflib
import hashlib
import ipaddress
import json
import os
import re
import shutil
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
from .htmltext import html_to_text, looks_like_html
from .shell import RunShellTool
from .websearch import WebSearchTool


class ReadFileTool:
    name = "read_file"
    description = "Read a file's contents (path-safety bounded)."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        path, span = _split_line_range(str(args["path"]))
        if span is None:
            content = pathsafety.safe_read_file(
                self._config.repo_root, path, readable_roots=self._config.readable_roots)
        else:
            # Slice the REAL file, never a pre-capped string: that was the
            # bug that made 61% of this very module unreachable.
            content = pathsafety.safe_read_lines(
                self._config.repo_root, path, start=span[0], end=span[1],
                readable_roots=self._config.readable_roots)
        ok = not content.startswith("[refused:")
        # A refusal is an error, not output. It used to be BOTH, so the
        # model was shown the same refusal twice in one result.
        return ToolResult(ok=ok, output=content if ok else "", error=None if ok else content)


_LINE_RANGE = re.compile(r"^(.*?):(\d+)-(\d+)$")


def _split_line_range(raw: str) -> tuple[str, tuple[int, int] | None]:
    """`path:START-END` -> (`path`, (START, END)); a bare path -> (path, None).

    The model reads files through a one-string marker (`READ_FILE: path`)
    and its side of a tool result is capped at ~8 KB, so without a way
    to ask for *part* of a file, anything past the cap was unreachable
    -- it could see that a 20 KB module was truncated and had no next
    move (observer agent round, 2026-09-07). Line numbers are 1-based
    and inclusive, like an editor's."""
    m = _LINE_RANGE.match(raw.strip())
    if m is None:
        return raw, None
    start, end = int(m.group(2)), int(m.group(3))
    if start < 1 or end < start:
        return raw, None
    return m.group(1), (start, end)


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


class SearchCodeTool:
    """Regex text search across `readable_roots` (the same path-safety
    boundary `read_file`/`list_dir` already enforce) -- the one gap
    those two can't close on their own: finding *where* something lives
    without already knowing the file or directory to look in. Read-only,
    with both a files-scanned and a matches-returned cap so one broad
    query can't turn into an unbounded scan or flood a step's own
    narration -- the same shape of cap `pathsafety.py`'s own
    `_MAX_LIST_ENTRIES`/`_MAX_READ_CHARS` already apply per-call.

    Shells out to `ripgrep` (`rg`) when it's on `PATH` -- faster and more
    correct (real binary-file detection, no Python-level directory walk)
    than the pure-Python fallback below, same "optional external binary,
    never a hard dependency" precedent `cognition/providers/
    claude_code_provider.py` already set for the `claude` CLI:
    `requirements.txt`'s own header ("Everything else is stdlib-only")
    is a hard project constraint, not a suggestion, so this can accelerate
    with `rg` but can never require it -- a fresh install with nothing
    beyond stdlib still gets a fully working (just slower) tool. `rg` is
    run with `--no-ignore` deliberately: without it, results would
    silently differ machine-to-machine depending on whether `.gitignore`
    processing is available, which the fallback path never respects
    either -- consistency across both paths matters more here than
    ignore-file awareness."""

    name = "search_code"
    description = (
        "Regex search file contents across the readable tree (path-safety bounded); "
        "returns path:line:text matches, capped in both files scanned and matches returned."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}

    def __init__(self, config: Config, *, ripgrep_path: str | None = None) -> None:
        self._config = config
        # Resolved once at construction (a tool instance lives for the
        # whole process, per `execution/service.py::start()` -- same
        # lifetime WebFetchTool's own rate-limit window already relies
        # on) rather than re-probing PATH on every call.
        self._rg = shutil.which("rg") if ripgrep_path is None else ripgrep_path

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        query = args["query"]
        try:
            re.compile(query)
        except re.error as exc:
            return ToolResult(ok=False, error=f"refused: {query!r} is not a valid regex: {exc!r}")

        root = self._config.repo_root.resolve()
        if self._rg:
            return self._run_ripgrep(query, root)
        return self._run_pure_python(query, root)

    def _run_ripgrep(self, query: str, root: Path) -> ToolResult:
        roots = [base for base in self._config.readable_roots if (root / base).is_dir()]
        if not roots:
            return ToolResult(ok=True, output="(no matches)", metadata={"matches": 0, "files_scanned": 0, "via": "ripgrep"})
        cmd = [
            self._rg, "--line-number", "--no-heading", "--with-filename", "--no-ignore",
            f"--max-filesize={self._config.search_max_file_bytes}",
            "-e", query, *roots,
        ]
        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, cwd=root, timeout=self._config.sandbox_timeout_s,
                stdin=subprocess.DEVNULL,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            # Never leaves the model with nothing -- degrade to the
            # pure-Python path rather than surface an `rg`-specific
            # failure for what's still a perfectly answerable query.
            return self._run_pure_python(query, root)
        if completed.returncode not in (0, 1):  # 1 == "no matches", not an error
            return self._run_pure_python(query, root)

        lines = [ln for ln in completed.stdout.splitlines() if "__pycache__" not in ln]
        truncated = len(lines) > self._config.search_max_matches
        lines = lines[: self._config.search_max_matches]
        output = "\n".join(lines) if lines else "(no matches)"
        if truncated:
            output += "\n...[capped -- narrow the query or the readable_roots searched]"
        return ToolResult(ok=True, output=output, metadata={"matches": len(lines), "via": "ripgrep"})

    def _run_pure_python(self, query: str, root: Path) -> ToolResult:
        pattern = re.compile(query)
        matches: list[str] = []
        scanned = 0
        truncated = False
        for base in self._config.readable_roots:
            base_path = root / base
            if not base_path.is_dir():
                continue
            for path in sorted(base_path.rglob("*")):
                if "__pycache__" in path.parts or not path.is_file():
                    continue
                try:
                    if path.stat().st_size > self._config.search_max_file_bytes:
                        continue
                except OSError:
                    continue
                scanned += 1
                if scanned > self._config.search_max_files_scanned:
                    truncated = True
                    break
                try:
                    text = path.read_text(errors="replace")
                except OSError:
                    continue
                rel = path.relative_to(root)
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if pattern.search(line):
                        matches.append(f"{rel}:{lineno}:{line.strip()[:200]}")
                        if len(matches) >= self._config.search_max_matches:
                            truncated = True
                            break
                if truncated:
                    break
            if truncated:
                break

        output = "\n".join(matches) if matches else "(no matches)"
        if truncated:
            output += "\n...[capped -- narrow the query or the readable_roots searched]"
        return ToolResult(ok=True, output=output, metadata={"matches": len(matches), "files_scanned": scanned, "via": "python"})


class FetchRefused(Exception):
    """No request was made (or its result is discarded): a disallowed
    scheme, a hostname that resolves to a private/internal address, a
    DNS failure, or an exhausted rate limit."""


def _decompress(raw: bytes, encoding: str) -> bytes:
    """Undo a `Content-Encoding` the server applied, whether or not it
    was asked to. Unknown or broken encodings return the bytes as they
    came, which is at worst the previous behaviour."""
    try:
        if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
            import gzip

            return gzip.decompress(raw)
        if encoding == "deflate":
            import zlib

            return zlib.decompress(raw)
    except Exception:  # noqa: BLE001 -- a bad body is still a body
        pass
    return raw


def _bearer_for(url: str, bearers: "tuple[tuple[str, str], ...]", env) -> str:
    """The bearer token for `url`, if one is configured for its host.

    Host-scoped on purpose, and matched on the exact host or a subdomain
    of it -- never a substring. A token belongs to one service; sending
    Hugging Face's to whatever host a model happened to name would hand
    a credential to an attacker who can get a URL in front of Sim (a
    page it fetched, a repo it read). An unset variable simply means no
    header, so a fetch that does not need one is unchanged."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return ""
    for suffix, var in bearers:
        suffix = suffix.lower()
        if host == suffix or host.endswith("." + suffix):
            return (env.get(var) or "").strip()
    return ""


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

        headers_out = {
            "User-Agent": self._config.web_fetch_user_agent,
            # Ask for plain bytes. Some servers compress anyway (python.org
            # sends gzip unrequested), so the body is checked below too.
            "Accept-Encoding": "identity",
        }
        token = _bearer_for(url, self._config.web_fetch_bearers, os.environ)
        if token:
            headers_out["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers_out)
        try:
            with self._opener(request, timeout=self._config.web_fetch_timeout_s) as response:
                status_code = getattr(response, "status", 200)
                encoding = ""
                charset = "utf-8"
                headers = getattr(response, "headers", None)
                if headers is not None:
                    encoding = (headers.get("Content-Encoding") or "").strip().lower()
                    charset = headers.get_content_charset() or "utf-8" if hasattr(headers, "get_content_charset") else "utf-8"
                raw = response.read(self._config.web_fetch_max_bytes * 4 + 1 if encoding else self._config.web_fetch_max_bytes + 1)
        except Exception as exc:  # noqa: BLE001 -- any network failure becomes a ToolResult, never a crash
            return ToolResult(ok=False, error=f"fetch failed: {exc!r}")

        # Found by trial 2026-09-07: python.org answered with
        # `Content-Encoding: gzip` and this handed the model the raw
        # compressed bytes as if they were text, `ok=True`. Sim narrated it
        # itself: "came back as unreadable gzip-compressed bytes". The
        # garbage was then stored into Memory as a fetched page.
        raw = _decompress(raw, encoding)
        truncated = len(raw) > self._config.web_fetch_max_bytes
        content = raw[: self._config.web_fetch_max_bytes].decode(charset, errors="replace")
        # Markup is not content. Measured on real pages: 74% of a docs
        # page, 87% of an arXiv abstract, and 99.5% of a JavaScript app
        # -- which returned 224 usable characters with `ok=True` and
        # told the model nothing was wrong (observer, 2026-09-08).
        js_shell = False
        raw_chars = len(content)
        if self._config.web_fetch_extract_text and looks_like_html(content):
            content, js_shell = html_to_text(content, url=url)
        return ToolResult(
            ok=True, output=content,
            metadata={
                "url": url, "status": status_code, "truncated": truncated,
                "sha256": hashlib.sha256(raw[: self._config.web_fetch_max_bytes]).hexdigest(),
                "fetched_at": ctx.clock.now(),
                "raw_chars": raw_chars, "text_chars": len(content), "js_shell": js_shell,
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


def _parse_mcp_proposal_json(text: str) -> dict[str, str] | None:
    """Live-caught: despite the tool's own `description` spelling out
    `key: value` lines, a model reached for JSON anyway (a very natural
    pull for structured data) -- `PROPOSE_MCP_SERVER: {"name": ...}`.
    Returns `None` (never raises) for anything that isn't a JSON object,
    so the caller falls through to the line-based parser; a real JSON
    object gets only its *recognized* keys extracted -- an unrecognized
    key (the live example used `"description"`, not one of this tool's
    real fields) is silently dropped, not guessed at, so validation
    still reports the real problem (a missing `reason`/`command`)
    honestly instead of papering over it with a wrong alias."""
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    fields: dict[str, str] = {}
    for key in _PROPOSAL_KEYS:
        value = obj.get(key)
        if value is None:
            continue
        fields[key] = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
    return fields


def _parse_mcp_proposal_text(text: str) -> dict[str, str]:
    """`key: value` lines, case-insensitive keys, lenient about a value
    (like `reason`) spanning multiple lines -- a model's own free-form
    output, not a format worth being strict about. A JSON object is
    accepted too (`_parse_mcp_proposal_json`), tried first."""
    from_json = _parse_mcp_proposal_json(text)
    if from_json is not None:
        return from_json
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
    path that ever writes the file.

    `reversibility="reversible"` (changed same day from `irreversible`,
    the creator: "sim should just create it, period ... remove any rule
    that prevents it"): this call only records a proposal, so gating the
    *proposal itself* behind Guardian's human-escalation path was
    redundant with the real gate one layer down and, worse, genuinely
    unanswerable at the time this was first written (`interface/
    service.py`'s own docstring on the `_on_prompt` fix has the story --
    `action.needs_human` had no consumer at all, so every escalation
    silently resolved "no" no matter what the human typed). Now that a
    real answer path exists it *could* go back to `irreversible`, but
    the creator's ask was to remove the friction, not just make it
    answerable, so this stays `reversible`: Guardian auto-allows it in
    guarded/trusted posture, same as `read_file`. The actual capability
    grant remains exactly as gated as before -- writing to `simorgh.
    toml` is `mcp approve`'s job alone, a human-only CLI action with no
    code path reachable from a tool call in any Guardian posture. That
    second gate is structural, not a trust-level policy, and stays
    unless the creator asks for that one specifically to go too.

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
    reversibility = "reversible"
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
            # pytest exit 5 is "no tests were collected", which is not a
            # failing suite -- it means the target has no tests yet.
            #
            # Live-caught 2026-09-07: asked for a brand-new skill, Sim
            # wrote it, ran the tests, got `no tests ran in 0.00s` and an
            # exit code of 5, read that as a failing suite, and then did
            # exactly what its instructions say -- refused to commit on a
            # red suite. The skill was left uncommitted on every attempt.
            # Reporting an honest "nothing to run" lets it proceed and
            # say so.
            no_tests = completed.returncode == _PYTEST_NO_TESTS_COLLECTED
            ok = completed.returncode == 0 or no_tests
            return ToolResult(
                ok=ok, output=completed.stdout,
                error=None if ok else f"exit_code={completed.returncode}",
                metadata={"stderr": completed.stderr, "exit_code": completed.returncode,
                          "duration_s": time.monotonic() - start},
            )


# pytest's own exit code for "no tests were collected". Not a failure.
_PYTEST_NO_TESTS_COLLECTED = 5


class RunTestsTool:
    """The `isolated_test_suite` gap `execution/README.md`'s "Deliberate
    scope cuts" names as deferred -- built here as the standalone
    capability itself (a real pytest run, isolated from the live working
    tree), not the full read/draft/test Cognition loop that gap was
    originally scoped for (that loop -- apply a draft to a copy, test it,
    feed failures back for revision -- is real follow-up work, not this
    tool's job). Copies the *current* repo state into a throwaway temp
    dir first and runs there, so a test run can never mutate real files
    or leave stray state behind, and two concurrent runs never race each
    other. `target` narrows to one path/pattern (a single test file or
    directory) -- the whole suite is the honest but slow default (~180s
    on this repo), so a caller that only touched one area should say so."""

    name = "run_tests"
    description = (
        "Run the test suite (or one target within it, e.g. a single test file/directory) "
        "against an isolated copy of the repo; never touches the real working tree."
    )
    read_only = True
    reversibility = "reversible"
    args_schema = {"type": "object", "required": ["target"], "properties": {"target": {"type": "string"}}}

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        target = (args.get("target") or "").strip() or "tests"
        if Path(target).is_absolute() or ".." in Path(target).parts:
            return ToolResult(ok=False, error=f"refused: {target!r} is not a safe relative target")

        timeout = min(ctx.constraints.get("timeout_s", self._config.test_timeout_s), self._config.test_timeout_s)
        start = time.monotonic()
        root = self._config.repo_root.resolve()
        cap = self._config.test_output_max_chars
        with tempfile.TemporaryDirectory(prefix="simorgh-tests-") as workdir:
            dest = Path(workdir) / "repo"
            try:
                shutil.copytree(root, dest, ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".git", ".simdata", "*.egg-info", ".pytest_cache",
                ))
            except OSError as exc:
                return ToolResult(ok=False, error=f"could not stage an isolated copy: {exc!r}")
            if not (dest / target).exists():
                return ToolResult(ok=False, error=f"refused: {target!r} does not exist in the repo")
            preexec = _apply_rlimits(self._config.test_cpu_seconds, self._config.test_memory_mb * 1024 * 1024) if resource else None
            try:
                completed = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", target], capture_output=True, text=True,
                    cwd=dest, timeout=timeout, preexec_fn=preexec, stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired as exc:
                return ToolResult(
                    ok=False, output=(exc.stdout or "")[-cap:], error="timeout",
                    metadata={"stderr": (exc.stderr or "")[-cap:], "duration_s": time.monotonic() - start},
                )
            except OSError as exc:
                return ToolResult(ok=False, error=f"could not run tests: {exc!r}")
            # Same reading as the isolated suite above: exit 5 is "no
            # tests were collected", which is not a failing suite. This is
            # the one the model itself calls, and reporting a new file's
            # missing tests as a failure is what stopped Sim committing
            # its first skill (live-caught 2026-09-07).
            no_tests = completed.returncode == _PYTEST_NO_TESTS_COLLECTED
            ok = completed.returncode == 0 or no_tests
            output = completed.stdout[-cap:]
            if no_tests:
                output = (output + "\n\n[no tests cover this target yet -- nothing was run]").strip()
            return ToolResult(
                ok=ok, output=output,
                error=None if ok else f"exit_code={completed.returncode}",
                metadata={"stderr": completed.stderr[-cap:], "exit_code": completed.returncode,
                          "no_tests_collected": no_tests,
                          "duration_s": time.monotonic() - start},
            )


def _python_syntax_problem(subject: str, code: str) -> str | None:
    """`None` if this is safe to write, else why it is not.

    Only `.py` files: a skill or a source patch has to import, and a file
    that does not parse is never what was wanted.
    """
    if not subject.endswith(".py"):
        return None
    try:
        ast.parse(code)
    except SyntaxError as exc:
        line = f" at line {exc.lineno}" if exc.lineno else ""
        return f"{exc.msg}{line}. Send only the file's code, nothing else."
    return None


# A rewrite that keeps fewer than this share of a file's non-blank lines
# is refused as content loss -- once the file is big enough for the loss
# to be real, not a 3-line stub being replaced.
_CONTENT_LOSS_KEEP_RATIO = 0.6
_CONTENT_LOSS_MIN_LINES = 12


def _content_loss(old: str, new: str) -> str | None:
    """`"33 of 48 lines"` when `new` drops too much of `old`, else None."""
    old_n = sum(1 for line in old.splitlines() if line.strip())
    new_n = sum(1 for line in new.splitlines() if line.strip())
    if old_n < _CONTENT_LOSS_MIN_LINES or new_n >= old_n * _CONTENT_LOSS_KEEP_RATIO:
        return None
    return f"{old_n - new_n} of {old_n} non-blank lines"


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
    problem = _python_syntax_problem(subject, code)
    if problem is not None:
        # Refusing beats writing a broken file, and the model gets a real
        # error it can act on rather than a silent success.
        #
        # Live-caught 2026-09-07, Sim's first skill: everything after the
        # first line of the marker payload becomes the file body, and the
        # model kept talking after its code -- so
        # `simorgh_skills/word_count.py` was written with a hallucinated
        # "[test results: 42 passed]" and a stray "You are Simorgh,
        # continue." pasted into it. The function above them was perfect;
        # the file would not import.
        return ToolResult(ok=False, error=f"refused: {subject} would not be valid Python -- {problem}")
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
    if already_existed and old_text:
        lost = _content_loss(old_text, code)
        if lost is not None:
            # Watched trial, 2026-09-07: asked to add one constant, the
            # model read lines 1-15 of a 48-line file and sent those 15
            # lines plus the constant as the "complete" file. Verification
            # caught it that time; this catches it before anything is
            # written. A rewrite that drops most of a file is almost never
            # the task, and when it is, saying so costs one more call.
            return ToolResult(ok=False, error=(
                f"refused: the new content for {subject} drops {lost} -- apply_source_patch replaces the "
                f"whole file. Read it all first, in ranges if it is long "
                f"(READ_FILE: {subject}:1-200, then :201-400, and so on -- each result tells you the "
                "true total), and send it back complete with your change. If you truly mean to remove "
                "that much, say so and send it again."
            ))
    target.parent.mkdir(parents=True, exist_ok=True)
    # A model's reply rarely ends in a newline, and writing it verbatim
    # left every patched file without its final one (observer,
    # 2026-09-08) -- a spurious diff line on every edit.
    target.write_text(code if code.endswith("\n") else code + "\n")
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
    # `file_create` for a path that did not exist: the session's cleanup
    # needs to know, because `git_discard` cannot restore an untracked
    # file and an abandoned new one was being left behind as a dirty tree.
    effects = (f"file_write:{subject}",) + (() if already_existed else (f"file_create:{subject}",))
    return ToolResult(
        ok=True, output=output, side_effects=effects,
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


class GitDiscardTool:
    """Throw away uncommitted changes to one path, back to HEAD.

    Live-caught 2026-09-07 by a trial designed to fail: asked to make a
    change that breaks the suite, Sim applied it, ran the tests, saw them
    fail, and correctly refused to commit -- exactly as instructed. Then
    it had nowhere to go. Its instructions say to use `git_revert`
    instead of leaving the tree broken, but `git_revert` undoes a
    *commit*, and there was no commit; the change was sitting
    uncommitted. It had been told to use a tool that could not do the
    job, so it left a broken working tree behind.

    This is the missing half of `apply_source_patch`: the way back from
    an applied change that turned out to be wrong.
    """

    name = "git_discard"
    description = "Discard uncommitted changes to one path, restoring it to the last commit."
    read_only = False
    # Reversible in the sense Guardian cares about: it only ever moves a
    # file back to something already committed, and it refuses outright
    # to touch a path git has no committed version of.
    reversibility = "reversible"
    args_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        subject = str(args.get("path", "")).strip().replace("\\", "/")
        if not subject:
            return ToolResult(ok=False, error="refused: name the path to discard")
        scopes = self._config.write_scopes_source + self._config.write_scopes_skills
        if ".." in Path(subject).parts or not pathsafety.in_write_scope(subject, write_scopes=scopes):
            return ToolResult(ok=False, error=f"refused: {subject!r} is outside the writable scope")
        root = self._config.repo_root
        run = lambda cmd: subprocess.run(  # noqa: E731
            cmd, cwd=root, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )
        known = run(["git", "ls-files", "--error-unmatch", subject])
        if known.returncode != 0:
            if args.get("created"):
                # The caller vouches this session brought the file into
                # existence. Removing it is then the *only* way to put the
                # tree back -- there is no committed version to restore.
                target = (root / subject).resolve()
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    return ToolResult(ok=False, error=f"could not remove {subject}: {exc}")
                return ToolResult(
                    ok=True, output=f"removed {subject}, which this session had created",
                    side_effects=(f"git_discard:{subject}",),
                )
            # An untracked file has no committed version to go back to.
            # Deleting it here would be a different, destructive act than
            # the one this tool advertises.
            return ToolResult(
                ok=False,
                error=f"refused: {subject} is not tracked by git, so there is nothing to restore it to",
            )
        result = run(["git", "checkout", "--", subject])
        if result.returncode != 0:
            return ToolResult(ok=False, error=(result.stderr or result.stdout).strip()[:400])
        return ToolResult(
            ok=True, output=f"discarded uncommitted changes to {subject}",
            side_effects=(f"git_discard:{subject}",),
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
        ReadFileTool(config), ListDirTool(config), SearchCodeTool(config), RunPythonSandboxedTool(config),
        RunTestsTool(config), ApplySourcePatchTool(config), GitCommitTool(config), GitRevertTool(config),
        GitDiscardTool(config),
        ApplySkillTool(config), WebFetchTool(config), WebSearchTool(config), ProposeMcpServerTool(),
        # Off unless `[execution] shell = true`: the one tool whose blast
        # radius is not bounded by its own arguments (execution/shell.py).
        *((RunShellTool(config),) if getattr(config, "shell", False) else ()),
    ]
