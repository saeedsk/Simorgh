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
import asyncio

import difflib
import hashlib
import importlib.util
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
import urllib.parse
import urllib.request
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

try:
    import resource
except ImportError:  # POSIX-only
    resource = None  # type: ignore[assignment]

from simorgh.contracts import topics
from simorgh.contracts.checkout import (staged_diff, 
    MANIFEST_NAME, TARGET_DJANGO_LABEL, ContainerCheckout, container_run_line, django_label,
    find_enclosing,
)
from simorgh.contracts.pytestfailures import failing_nodeids, marker_for, strip_ansi
from simorgh.contracts.scratch import is_scratch
from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import ToolContext, ToolResult

from . import pathsafety
from .config import Config
from .htmltext import html_to_text, looks_like_bot_challenge, looks_like_html
from .netsafety import FetchRefused, validate_public_http_url, wait_note
from .doctext import document_to_text
from .geocode import GeocodeTool
from .packages import FindPackageTool, InstallPackageTool
from .pdftext import looks_like_pdf, pdf_to_text
from .realestate import RealEstateListingsTool
from .script import RunScriptTool
from .knowledge.tools import knowledge_tools
from .pim.tools import pim_tools
from .energy.tools import energy_tools
from .home.tools import home_tools
from .home.cameras import cameras_tools
from .home.ring import ring_tools
from .media.tools import media_tools
from .security.tools import security_tools
from .notify import NotifyTool
from .remote import RunRemoteTool
from .container import RunContainerTool
from .render import BrowsePageTool, RenderPageTool

# A PDF's bytes are mostly fonts and images, so the cap that bounds how
# much TEXT a fetch may return is the wrong ceiling for one. What
# matters is the text that comes out, which `pdf_to_text`'s page limit
# already bounds.
_PDF_MAX_BYTES = 60_000_000
# HTML has the same shape of problem, one size down: `web_fetch_max_bytes`
# (200,000) used to cap the RAW bytes before extraction ever ran, so a
# real page lost most of its content with no marker saying so. A live
# fetch of docs.python.org's asyncio page (observer, 2026-09-08) is
# 177,075 bytes -- under the cap, so it survived by luck; a page even a
# little larger would have been cut mid-tag with the loss invisible.
# Extraction needs the WHOLE document for the same reason `pdf_to_text`
# does (a table of contents, a byline, the actual body copy can all sit
# past 200 KB of nav and script), so read a much bigger raw budget when
# text extraction is going to run, then cap the EXTRACTED TEXT --
# `web_fetch_max_bytes` characters of it -- with an honest truncation
# marker instead of cutting the source silently.
_HTML_MAX_RAW_BYTES = 10_000_000
from .shell import RunShellTool
from .websearch import WebSearchTool


def tool_root(config: Config, ctx: ToolContext | None, path: str = "") -> Path:
    """The tree a call's paths resolve against.

    A task working in its own worktree (execution/worktree.py) carries
    that tree on `ctx.root`, set by the service from the task id, and
    every source path -- read, search, patch, test, commit -- belongs
    there. Scratch does not: `workspace/` is the one place a long piece
    of work keeps notes across tasks, and a worktree is removed the
    moment its task lands, so scratch stays on the live tree whichever
    tree the task is editing.
    """
    root = getattr(ctx, "root", None) if ctx is not None else None
    if root is None or (path and is_scratch(path)):
        return config.repo_root
    return Path(root)


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
        # In a thread, not inline. Reading a file used to be cheap enough
        # that a synchronous call in an `async def` was harmless; since
        # doctext.py, a `.docx`/`.xlsx`/PDF read runs a real parser with
        # NO await points inside it. An observer proved the consequence
        # on 2026-09-09: a zip bomb under the size cap pushed RSS past
        # 5.7GB while a sibling task never got a single tick, and
        # Execution's own `asyncio.wait_for` timeout could not fire --
        # cancellation only lands at an await point, so the whole
        # service froze for as long as the parse ran, not just this
        # action. `doctext` now refuses the bomb itself; this makes the
        # timeout real for every other slow file.
        if span is None:
            content = await asyncio.to_thread(
                pathsafety.safe_read_file,
                tool_root(self._config, ctx, path), path, readable_roots=self._config.readable_roots)
        else:
            # Slice the REAL file, never a pre-capped string: that was the
            # bug that made 61% of this very module unreachable.
            content = await asyncio.to_thread(
                pathsafety.safe_read_lines,
                tool_root(self._config, ctx, path), path, start=span[0], end=span[1],
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
        content = pathsafety.safe_list_dir(
            tool_root(self._config, ctx, args.get("path", "")), args.get("path", ""),
            readable_roots=self._config.readable_roots)
        ok = not content.startswith("[refused:")
        return ToolResult(ok=ok, output=content, error=None if ok else content)


class SelfMapTool:
    """Ask the World Model what you are actually made of, instead of
    guessing from the filesystem. Wraps `world.env.query`
    (worldmodel/service.py's `capability_map` facet) over the bus -- the
    same inventory Curiosity's own sampler reads -- so a self-knowledge
    question ("where does your code live", "what subsystems make you
    up") has a direct, correct answer instead of falling back to
    `list_dir` and wandering the tree by hand.

    Live-caught 2026-09-08: asked exactly that question, the model never
    touched `world.env.query` -- nothing model-callable reached it -- so
    it called `list_dir`, wandered into `src/` (the retired v1 tree,
    left readable but not what runs), and answered with v1's six
    directories mislabeled as living under `simorgh/`. This tool gives
    it the real answer in one call; `list_dir`/`search_code` are still
    there for anything this facet does not cover.
    """

    name = "self_map"
    description = (
        "The authoritative list of your own subsystems and files, straight from "
        "your world model -- not a filesystem guess. Returns the top-level "
        "packages under simorgh/ (the live v2 tree you actually run) and, per "
        "package, the modules in it. Pass `area` to see just one package's "
        "modules. This does NOT include src/, which is retired v1 code kept "
        "readable for reference but not what runs today."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {"area": {"type": "string"}}}

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        if ctx.bus is None:
            return ToolResult(ok=False, error="no bus available to reach the world model")
        # Always ask for the WHOLE map first and filter locally, rather
        # than passing a caller-given `area` straight to the facet: a
        # marker-shaped call (`SELF_MAP: <whatever the model typed>`)
        # hands this whatever free text followed the marker, not
        # necessarily a real area name -- live-caught 2026-09-08, asked
        # "what subsystems make you up", the model wrote
        # `SELF_MAP: full map of subsystems and top-level files`, that
        # string matched no real area, the facet came back with 0
        # modules, and the model treated the empty result as the tool
        # having failed and fell back to list_dir anyway.
        try:
            reply = await ctx.bus.request(
                ctx.bus.new(topics.WORLD_ENV_QUERY, {"what": "capability_map", "args": {}}), timeout=5.0)
        except TimeoutError:
            return ToolResult(ok=False, error="world model did not respond in time")
        if not reply.payload.get("ok", False):
            err = reply.payload.get("error", {})
            return ToolResult(ok=False, error=err.get("detail") or repr(err) or "world model query failed")
        areas = reply.payload.get("areas", [])
        by_area = reply.payload.get("modules_by_area", {})
        wanted = str((args or {}).get("area") or "").strip().lower()
        match = next((a for a in areas if a.lower() == wanted), None) if wanted else None
        if match:
            modules = by_area.get(match, [])
            text = f"area: {match}\nmodules ({len(modules)}):\n" + "\n".join(f"  {m}" for m in modules)
            return ToolResult(ok=True, output=text, metadata={"area": match, "modules": modules})
        lines = [f"You are made of {len(areas)} subsystems under simorgh/ (src/ is retired v1, not this):"]
        for a in areas:
            lines.append(f"  {a} ({len(by_area.get(a, []))} files)")
        if wanted:
            lines.append(f"\n(no subsystem matched area={wanted!r} -- showing the full map instead)")
        return ToolResult(ok=True, output="\n".join(lines), metadata={"areas": areas, "modules_by_area": by_area})


_NO_MATCHES = "(no matches)"


def _no_match_note(config) -> str:
    """"(no matches)" reads as "the term is not there". For a repo whose
    readable roots include a directory of PDFs, that is not what it
    means: a text search cannot see inside a PDF at all.

    An observer watched the consequence on 2026-09-08. Three searches
    for terms that are unmistakably in `papers/` all came back
    `(no matches)` with `ok=True`; the session spent 11 of 28 steps
    circling, and then FABRICATED a quotation from a paper it had never
    read, inventing both the line numbers and the figure. The scaffold
    points the model here first ("cheaper than reading whole files"), so
    an empty answer from this tool is unusually persuasive.
    """
    roots = getattr(config, "readable_roots", ())
    repo_root = getattr(config, "repo_root", None)
    if repo_root is None:
        return _NO_MATCHES
    holding: list[str] = []
    for root in roots:
        try:
            found = sorted((repo_root / root).glob("*.pdf"))
        except OSError:
            continue
        if found:
            holding.append(f"{root}/ ({len(found)} PDFs)")
    if not holding:
        return _NO_MATCHES
    return (f"{_NO_MATCHES} -- note that this search reads text files only, and "
            f"{', '.join(holding)} cannot be searched this way. Use READ_FILE on a "
            f"specific document, or LIST_DIR to see what is there.")


def _rg_line_is_credential(line: str, root: Path | None = None,
                           readable_roots: tuple[str, ...] = ()) -> bool:
    """`ripgrep` output is `path:lineno:text`; check the path prefix
    against the same rule `resolve_safe_path` (and `read_file`) enforce,
    so `search_code` cannot grep a `.env`/`credentials.json`/etc. that a
    direct `read_file` on the same path would refuse. `rg`'s own default
    hidden-file skip masked the dotfile case (`.env`) by accident but
    never covered a non-hidden name like `credentials.json` -- found
    live, 2026-09-08.

    The name alone was not enough: a link is named whatever you like.
    With a root, this asks the full question -- resolution, containment
    and extra names -- because an observer got
    `workspace/notes.txt:1:SECRET=hunter2` out of this backend while
    `read_file` on the same path was refused (2026-09-10).

    And the FULL question was still asked about the wrong path. The
    split was on the first colon, and a colon is a legal character in a
    filename on every filesystem this runs on, so
    `workspace/notes:1.env:1:SECRET=hunter2` was checked as
    `workspace/notes` -- a name that is neither credential-shaped nor a
    real file, so every check passed and the secret came back, while
    `read_file` on the same path answered "looks like a credentials
    path". Reproduced 2026-09-10 against the real `rg`. `rg --null`
    ends the path with a NUL, which no filename can contain, so
    `_rg_split` never has to guess; and a path that does not name a real
    file under the root is refused rather than waved through, because
    the only way to get one is for this parse to have gone wrong."""
    path_part = _rg_split(line)[0]
    if root is not None:
        candidate = root / path_part
        if not candidate.is_file():
            return True     # not a path we parsed correctly -- fail closed
        return pathsafety.hides_a_credential(root, candidate, readable_roots=readable_roots)
    return pathsafety.looks_like_credential_path(Path(path_part).parts)


#: `rg --null` writes `path\0lineno:text`. A NUL is the one byte a POSIX
#: filename cannot contain, which is the whole reason for asking for it.
#: Without it the path had to be guessed off the first colon, and a
#: colon in a filename made the guess wrong in the direction that leaks.
def _rg_split(line: str) -> tuple[str, str]:
    """`(path, rest)` for one `rg --null` output line."""
    path, sep, rest = line.partition("\0")
    if not sep:
        # An `rg` too old for `--null`, or output from somewhere else:
        # fall back to the first-colon guess rather than refuse
        # everything, and let the `is_file` check above catch what the
        # guess gets wrong.
        path, _, rest = line.partition(":")
    return path, rest


def _rg_display(line: str) -> str:
    """The NUL back to the `path:lineno:text` the model is shown."""
    path, rest = _rg_split(line)
    return f"{path}:{rest}" if rest else path


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

        root = tool_root(self._config, ctx).resolve()
        # Both in a worker thread: ripgrep is a subprocess and the pure
        # Python fallback walks the whole tree, and either one run inline
        # here holds the event loop for its duration (observer swe-01,
        # 2026-09-10 -- the same freeze `run_tests` and `run_shell` had).
        if self._rg:
            return await asyncio.to_thread(self._run_ripgrep, query, root)
        return await asyncio.to_thread(self._run_pure_python, query, root)

    def _run_ripgrep(self, query: str, root: Path) -> ToolResult:
        roots = [base for base in self._config.readable_roots if (root / base).is_dir()]
        if not roots:
            return ToolResult(ok=True, output=_no_match_note(self._config),
                              metadata={"matches": 0, "files_scanned": 0, "via": "ripgrep"})
        cmd = [
            self._rg, "--line-number", "--no-heading", "--with-filename", "--no-ignore",
            "--null",
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

        lines = [
            _rg_display(ln) for ln in completed.stdout.splitlines()
            if "__pycache__" not in ln and not _rg_line_is_credential(
                ln, root, self._config.readable_roots)
        ]
        truncated = len(lines) > self._config.search_max_matches
        lines = lines[: self._config.search_max_matches]
        output = "\n".join(lines) if lines else _no_match_note(self._config)
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
                if pathsafety.hides_a_credential(root, path,
                                                 readable_roots=self._config.readable_roots):
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

        output = "\n".join(matches) if matches else _no_match_note(self._config)
        if truncated:
            output += "\n...[capped -- narrow the query or the readable_roots searched]"
        return ToolResult(ok=True, output=output, metadata={"matches": len(matches), "files_scanned": scanned, "via": "python"})


# `FetchRefused`/`validate_public_http_url` live in `netsafety.py` now
# (imported at module top) -- `render_page` needs the exact same SSRF
# guard for its own remote-URL case, and importing it back from here
# would be circular since this module imports `.render` transitively
# via `builtin_tools`.


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
        # Per host, plus a whole-tool ceiling. See `_enforce_rate_limit`.
        self._recent_calls: deque[float] = deque()
        self._recent_by_host: dict[str, deque[float]] = {}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        url = args["url"]
        try:
            self._validate_url(url)
            self._enforce_rate_limit(ctx, url)
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
                # A PDF has to be read WHOLE or not at all: pypdf reads
                # the cross-reference table from the end of the file, so
                # a PDF cut at the text cap parses to nothing. Peek at
                # the first bytes, and give a PDF its own much larger
                # ceiling. Before this, every paper in `papers/` (0.57 to
                # 17 MB) came back as "this PDF could not be parsed ...
                # it may be encrypted or corrupt" -- a false accusation
                # against the document, for a cap of ours (observer,
                # 2026-09-08).
                head = response.read(1024)
                if looks_like_pdf(head):
                    budget = _PDF_MAX_BYTES
                elif self._config.web_fetch_extract_text and looks_like_html(head.decode(charset, errors="replace")):
                    # Same reasoning as the PDF cap just above: extraction
                    # needs the whole document, so give a page that is
                    # going to be extracted a raw budget sized for that,
                    # not the (much smaller) budget meant to bound what
                    # the model ultimately sees.
                    budget = _HTML_MAX_RAW_BYTES
                else:
                    budget = self._config.web_fetch_max_bytes
                raw = head + response.read(budget * 4 + 1 if encoding else budget + 1)
        except Exception as exc:  # noqa: BLE001 -- any network failure becomes a ToolResult, never a crash
            return ToolResult(ok=False, error=f"fetch failed: {exc!r}")

        # Found by trial 2026-09-07: python.org answered with
        # `Content-Encoding: gzip` and this handed the model the raw
        # compressed bytes as if they were text, `ok=True`. Sim narrated it
        # itself: "came back as unreadable gzip-compressed bytes". The
        # garbage was then stored into Memory as a fetched page.
        raw = _decompress(raw, encoding)

        # A PDF is bytes all the way down, so it has to be handled before
        # anything decodes it as text. This used to return `%PDF-1.5`
        # followed by binary stream data with `ok=True` -- the GAIA
        # observer's top-ranked gap, since a benchmark that attaches
        # papers cannot be answered by a system that cannot read one
        # (2026-09-08). The whole body is used, not the capped prefix: a
        # PDF cut in half parses as nothing at all.
        if self._config.web_fetch_extract_text and looks_like_pdf(raw):
            pdf_truncated = len(raw) > _PDF_MAX_BYTES
            if pdf_truncated:
                raw = raw[:_PDF_MAX_BYTES]
            text, problem = pdf_to_text(raw, source=url)
            if pdf_truncated and not text:
                # Say whose fault it is. "Corrupt or encrypted" about a
                # perfectly good paper sends the model off to find
                # another copy of a document that was never the problem.
                problem = (f"this PDF is larger than the {_PDF_MAX_BYTES // 1_000_000} MB fetch limit, "
                           "so only part of it arrived and it cannot be parsed. Try a smaller copy, "
                           "an HTML version, or the abstract page.")
            return ToolResult(
                ok=not (problem and not text), output=text or "", error=problem,
                metadata={
                    "url": url, "status": status_code, "truncated": pdf_truncated, "kind": "pdf",
                    "sha256": hashlib.sha256(raw).hexdigest(), "fetched_at": ctx.clock.now(),
                    "raw_chars": len(raw), "text_chars": len(text), "js_shell": False,
                },
            )

        # A spreadsheet, document or image fetched over HTTP gets the
        # same treatment `read_file` gives it on disk (doctext.py) --
        # otherwise a link to an .xlsx of the very data a task is about
        # comes back as binary noise with ok=True.
        if self._config.web_fetch_extract_text:
            handled = document_to_text(raw, name=urlparse(url).path)
            if handled is not None:
                text, problem = handled
                return ToolResult(
                    ok=not (problem and not text), output=text or "", error=problem or None,
                    metadata={
                        "url": url, "status": status_code, "truncated": False, "kind": "document",
                        "sha256": hashlib.sha256(raw).hexdigest(), "fetched_at": ctx.clock.now(),
                        "raw_chars": len(raw), "text_chars": len(text), "js_shell": False,
                    },
                )

        # Decode the WHOLE raw body, not a byte-capped prefix: extraction
        # used to run on `raw[:web_fetch_max_bytes]` (200 KB), so a long
        # real page lost most of its content before extraction ever saw
        # it, with nothing in the output saying so. A live fetch of
        # nfl.com (observer, 2026-09-08) came back as 3,872,038 bytes;
        # capped first, extraction had 200,000 of those to work with and
        # produced 4,708 characters of text -- capped after extraction
        # (below), the same fetch yields 90,520.
        full_text = raw.decode(charset, errors="replace")
        raw_chars = len(full_text)
        # Markup is not content. Measured on real pages: 74% of a docs
        # page, 87% of an arXiv abstract, and 99.5% of a JavaScript app
        # -- which returned 224 usable characters with `ok=True` and
        # told the model nothing was wrong (observer, 2026-09-08).
        js_shell = False
        challenge = False
        if self._config.web_fetch_extract_text and looks_like_html(full_text):
            content, js_shell = html_to_text(full_text, url=url)
            challenge = looks_like_bot_challenge(full_text, content)
            raw_truncated = len(raw) > _HTML_MAX_RAW_BYTES
            text_truncated = len(content) > self._config.web_fetch_max_bytes
            if text_truncated:
                cut = len(content) - self._config.web_fetch_max_bytes
                source_note = (
                    f" The source page itself was cut at the {_HTML_MAX_RAW_BYTES:,}-byte fetch "
                    f"limit before this text was extracted from it."
                    if raw_truncated else ""
                )
                content = (
                    content[: self._config.web_fetch_max_bytes]
                    + f"\n\n[... truncated: {cut:,} more characters of extracted text were cut off "
                      f"at the {self._config.web_fetch_max_bytes:,}-character limit.{source_note}]"
                )
            truncated = raw_truncated or text_truncated
        else:
            content = full_text[: self._config.web_fetch_max_bytes]
            truncated = len(raw) > self._config.web_fetch_max_bytes
        if challenge:
            # A 200 that is really "prove you are a browser" is not
            # content, and returning it as content is the whole
            # "succeeds while saying nothing true" failure: an observer
            # watched Sim read pypi.org's challenge page as httpx's
            # project page (2026-09-10).
            return ToolResult(
                ok=False,
                error=(f"{url} answered with an anti-bot challenge page instead of its content "
                       f"(HTTP {status_code}, {len(content)} characters of text). The site is "
                       f"refusing automated requests; try another source, or an API it publishes."),
                metadata={"url": url, "status": status_code, "bot_challenge": True,
                          "raw_chars": raw_chars, "text_chars": len(content)},
            )
        return ToolResult(
            ok=True, output=content,
            metadata={
                "url": url, "status": status_code, "truncated": truncated,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "fetched_at": ctx.clock.now(),
                "raw_chars": raw_chars, "text_chars": len(content), "js_shell": js_shell,
            },
        )

    def _validate_url(self, url: str) -> None:
        validate_public_http_url(
            url, allow_private=self._config.web_fetch_allow_private_networks, resolver=self._resolver)

    def _enforce_rate_limit(self, ctx: ToolContext, url: str = "") -> None:
        """Polite to each site, and not a straitjacket across all of them.

        The limit used to be one bucket for the whole internet: 30
        fetches an hour, whatever they were of. That is far stricter
        than politeness needs -- 30 requests an hour to one host is
        courteous, 30 across every host there is means one thorough
        piece of research locks the tool for everything that comes
        after it. Measured on a GAIA run, 2026-09-10: 103 of 682 steps
        were fetches this limiter refused, and questions late in the run
        met a bucket that questions early in the run had emptied.

        So the per-host limit keeps the old number and the old promise,
        and a separate, much larger ceiling still bounds the tool as a
        whole so a runaway loop cannot hammer the network.
        """
        now = ctx.clock.now()
        host = ""
        try:
            host = (urllib.parse.urlsplit(url).hostname or "").lower()
        except ValueError:
            host = ""

        def _trim(calls) -> None:
            cutoff = now - self._config.web_fetch_window_s
            while calls and calls[0] < cutoff:
                calls.popleft()

        # `.get`, not `setdefault`: the row used to be created before
        # both limit checks, and both checks RAISE -- so every refused
        # fetch of a host never seen before left a permanent empty row
        # that the cleanup at the end of this method never reached.
        # Measured by an observer, 2026-09-10: with the ceiling
        # saturated, 5,000 refused fetches of 5,000 distinct hosts left
        # 5,240 rows, 5,000 of them empty. The limiter was growing the
        # table it refuses from.
        per_host = self._recent_by_host.get(host) or deque()
        _trim(per_host)
        _trim(self._recent_calls)

        if len(per_host) >= self._config.web_fetch_max_calls:
            raise FetchRefused(
                f"rate limit exceeded: {len(per_host)}/{self._config.web_fetch_max_calls} fetches "
                f"of {host or 'this host'} in the last {self._config.web_fetch_window_s:.0f}s. "
                f"{wait_note(per_host[0] + self._config.web_fetch_window_s - now)} "
                f"Retrying the same fetch before then will be refused the same way -- read a "
                f"different source, or answer from what you already have."
            )
        if len(self._recent_calls) >= self._config.web_fetch_max_total_calls:
            raise FetchRefused(
                f"rate limit exceeded: {len(self._recent_calls)}/"
                f"{self._config.web_fetch_max_total_calls} fetches in the last "
                f"{self._config.web_fetch_window_s:.0f}s across every host. "
                f"{wait_note(self._recent_calls[0] + self._config.web_fetch_window_s - now)} "
                f"Answer from what you have already read."
            )
        # Recorded only once the call is actually allowed.
        per_host.append(now)
        self._recent_by_host[host] = per_host
        self._recent_calls.append(now)
        # Forget hosts whose calls have all fallen out of the window.
        # This used to test `if not calls`, which could never be true:
        # only the host being fetched is ever trimmed, so every other
        # host's deque kept its stale timestamps and its entry forever
        # (observer, 2026-09-10: 500 hosts, window long past, 240
        # entries still held). Bounded memory, but unbounded is
        # unbounded.
        cutoff = now - self._config.web_fetch_window_s
        for name in [h for h, calls in self._recent_by_host.items()
                     if not calls or calls[-1] < cutoff]:
            if name != host:
                self._recent_by_host.pop(name, None)


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


def pytest_parallel_args(target: Path) -> list[str]:
    """`["-n", "auto"]` when pytest-xdist is importable and the target is
    a directory, else nothing.

    The suite is 3000+ tests and ran serially: 250s per call, and a patch
    task calls `run_tests` twice, so one trial spent 500s inside this
    tool alone -- the `breaks-the-suite` trial blew its 900s cap on
    exactly that (loader gate, 2026-09-08). Across 12 cores the same
    suite takes 57s with the identical pass/fail result. It is a
    separate-process split, not threads: the GIL makes threads useless
    for CPU-bound assertions, and xdist's workers are real interpreters.

    A single test FILE stays serial: spawning a dozen workers costs a
    second or two of startup, more than a small file takes to run.
    Optional on purpose -- `pytest-xdist` is in requirements.txt but a
    machine without it must still be able to run its tests.
    """
    if importlib.util.find_spec("xdist") is None or not target.is_dir():
        return []
    return ["-n", "auto"]


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
                # In a worker thread: a tool's `run` is a coroutine on the
                # event loop's own thread, and a synchronous `subprocess.run`
                # here froze the whole process for the length of the child
                # -- no narration, no reply to anything typed, no Ledger
                # writes (observer swe-01, 2026-09-10, through the terminal).
                completed = await asyncio.to_thread(
                    subprocess.run,
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


class RunJsSandboxedTool:
    """The Node/JS twin of `run_python_sandboxed`: same fresh-subprocess,
    empty-env, temp-cwd, CPU/mem/time-bounded isolation, no repo access
    -- because Simorgh's own generated-game trials (2026-09-09) showed a
    real gap: `SyntaxCheck` (verification/checks/syntax.py) parses only
    Python via `ast.parse`, so a task that writes or reasons about
    JavaScript had no way to actually run it and see what happens,
    only read it back and guess. `node` is resolved to an absolute
    path once at construction time since the subprocess runs with an
    empty environment (no PATH for execvp to search)."""

    name = "run_js_sandboxed"
    description = "Run JavaScript code with Node in an isolated, resource-bounded subprocess with no repo access."
    read_only = True
    reversibility = "reversible"
    args_schema = {"type": "object", "required": ["code"], "properties": {"code": {"type": "string"}}}

    _UNSET = object()

    def __init__(self, config: Config, *, node_path: str | None = _UNSET) -> None:
        self._config = config
        self._node = shutil.which("node") if node_path is self._UNSET else node_path

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        if not self._node:
            return ToolResult(ok=False, error="refused: no `node` executable found on this machine")
        code = args["code"]
        timeout = min(ctx.constraints.get("timeout_s", self._config.sandbox_timeout_s), self._config.sandbox_timeout_s)
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="simorgh-sandbox-js-") as workdir:
            script = Path(workdir) / "code.js"
            script.write_text(code)
            preexec = _apply_rlimits(self._config.sandbox_cpu_seconds, self._config.sandbox_memory_mb * 1024 * 1024) if resource else None
            try:
                completed = await asyncio.to_thread(   # off the loop thread, see RunPythonTool
                    subprocess.run,
                    [self._node, str(script)], capture_output=True, text=True,
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


# pytest's own exit code for "no tests were collected". Not a failure.
_PYTEST_NO_TESTS_COLLECTED = 5
# pytest's exit code for a usage error -- what a non-Python target
# produces ("file or directory not found"). Only ever read as "nothing
# to run" when the target really is not Python; a genuine usage error on
# a Python target (a bad flag, an unreadable conftest) stays a failure.
_PYTEST_USAGE_ERROR = 4


def nested_git_root(root: Path, relative: str) -> tuple[Path, str] | None:
    """`(repo, path relative to it)` when `root/relative` sits inside a git
    repository nested strictly below `root`; else None.

    `workspace/swebench/<id>/` is a whole other project, `.git` and all,
    and `workspace/` is gitignored -- so from Simorgh's repository a
    change in there does not exist. `git_commit` on such a path answered
    `nothing_to_commit` (2026-09-10) and Sim, which had been told by the
    verifier to commit, went round again. A path belongs to the nearest
    repository above it, and that is where git runs.
    """
    root = root.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    for candidate in [target, *target.parents]:
        if candidate == root:
            return None
        if (candidate / ".git").exists():
            return candidate, target.relative_to(candidate).as_posix()
    return None


def _docker_run(args: list[str], *, timeout: float) -> tuple[int, str]:
    """`(exit code, merged output)` of one docker command. A seam, so a
    test can stand in for the daemon."""
    # `stdout=PIPE` + `stderr=STDOUT`, not `capture_output` -- the two are
    # mutually exclusive and `subprocess.run` raises ValueError on the
    # combination. The first version had both, and every in-container
    # `run_tests` in run three died with that error before Docker was
    # ever invoked, unseen by a test that had stubbed this seam (2026-09-10).
    # `test_the_seam_really_runs` now executes it for real.
    try:
        done = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout
        return 124, out.decode("utf-8", "replace") if isinstance(out, bytes) else (out or "")
    except OSError as exc:
        return 127, repr(exc)
    return done.returncode, done.stdout or ""


def _checkout_patch(checkout: Path, base: str, *, timeout: float = 120.0) -> tuple[str, str]:
    """`(patch, problem)`: everything the checkout differs from `base` by,
    committed or not, tests included -- this is for RUNNING the tests,
    not scoring them, so nothing is excluded here but the manifest,
    which is ours and a file the image never had. Read through a private
    index (`contracts.checkout.staged_diff`), so two runs in flight on
    one checkout never fight over `.git/index.lock`."""
    return staged_diff(checkout, base, exclude=(MANIFEST_NAME,), timeout=timeout)


# What an isolated test copy leaves out: nothing a test reads, and most
# of the bytes. NOT "ledger": that pattern would also drop the
# `simorgh/ledger` package and its tests.
_ISOLATED_COPY_IGNORE = ("__pycache__", "*.pyc", ".git", ".simdata", "*.egg-info", ".pytest_cache",
                         "papers", "scratchpad", ".simorgh")


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

    @property
    def timeout_s(self) -> float:
        """How long the execution service should wait for one call.

        The service bounds every tool with its own `default_timeout_s`
        (60s) unless the approval carries a constraint, and nothing ever
        sets one -- so an in-container run under amd64 emulation was
        being cut at 60s from outside while this tool believed it had
        `test_timeout_s`. The margin is so this tool's own subprocess
        timeout fires first and returns real output, not the service's
        bare "timeout"."""
        return self._config.test_timeout_s + 30.0

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        target = (args.get("target") or "").strip() or "tests"
        if Path(target).is_absolute() or ".." in Path(target).parts:
            return ToolResult(ok=False, error=f"refused: {target!r} is not a safe relative target")

        timeout = min(ctx.constraints.get("timeout_s", self._config.test_timeout_s), self._config.test_timeout_s)
        start = time.monotonic()
        root = tool_root(self._config, ctx, target).resolve()
        cap = self._config.test_output_max_chars
        nested = find_enclosing(root, target)
        if nested is not None:
            checkout, inner = nested
            manifest = ContainerCheckout.read(checkout)
            if manifest is not None:
                return await asyncio.to_thread(
                    self._run_in_container, checkout, inner, manifest, timeout=timeout, start=start)
        # In a thread, like the container path above -- and unlike this
        # path until 2026-09-10. `subprocess.run` (and the `copytree`
        # before it) ran inline in this coroutine, which is to say ON
        # the event loop's thread: for the whole of a full-suite run
        # (up to `test_timeout_s`, 300s) nothing else in the process
        # moved. Seen through the terminal by an observer: `benchmark`
        # typed mid-run got its reply four minutes later, no narration,
        # the Ledger not written for the duration, and then -- because
        # bus handler deadlines had expired while the loop was frozen --
        # the worker's own session was cancelled mid-verify and a
        # 40-line traceback landed on the prompt. A tool "isolated from
        # the live working tree" was not isolated from the live loop.
        return await asyncio.to_thread(self._run_isolated, target, timeout=timeout, start=start, root=root)

    def gate(self, root: Path) -> ToolResult:
        """The whole suite against `root`, for `worktree_land`: the same
        isolated run the model gets, on the tree about to become main.
        Blocking; the caller threads it."""
        return self._run_isolated("tests", timeout=self._config.test_timeout_s, start=time.monotonic(),
                                  root=Path(root).resolve())

    def failing_alone(self, root: Path, nodeids: tuple[str, ...]) -> frozenset[str] | None:
        """Which of `nodeids` still fail when run again, alone, on a copy
        of `root`; None for no opinion (a run that could not happen).
        `worktree_land` asks this of the rebased tree and of main after
        a red gate, so a test that only fails under a whole-suite load,
        or that is red on main already, does not refuse a landing.
        Blocking; the caller threads it."""
        if not nodeids:
            return frozenset()
        root = Path(root).resolve()
        with tempfile.TemporaryDirectory(prefix="simorgh-rerun-") as workdir:
            dest = Path(workdir) / "repo"
            try:
                shutil.copytree(root, dest, ignore=shutil.ignore_patterns(*_ISOLATED_COPY_IGNORE))
            except OSError:
                return None
            try:
                done = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     "--continue-on-collection-errors", *nodeids],
                    capture_output=True, text=True, cwd=dest, timeout=self._config.test_timeout_s,
                    stdin=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            if done.returncode == _PYTEST_USAGE_ERROR:
                return None
            if done.returncode == 0:
                return frozenset()
            return frozenset(failing_nodeids(done.stdout)) & frozenset(nodeids)

    def _run_isolated(self, target: str, *, timeout: float, start: float, root: Path | None = None) -> ToolResult:
        """Copy the repo, run pytest there, read the result. Blocking by
        design: `run` hands it to a worker thread."""
        root = (root or self._config.repo_root).resolve()
        cap = self._config.test_output_max_chars
        with tempfile.TemporaryDirectory(prefix="simorgh-tests-") as workdir:
            dest = Path(workdir) / "repo"
            try:
                # `papers/` (109 MB of PDFs) and the observers' scratch
                # area were copied into every isolated test run and no
                # test reads either; the copy is 17 MB without them.
                # NOT "ledger": that pattern would also drop the
                # `simorgh/ledger` package and its tests.
                shutil.copytree(root, dest, ignore=shutil.ignore_patterns(*_ISOLATED_COPY_IGNORE))
            except OSError as exc:
                return ToolResult(ok=False, error=f"could not stage an isolated copy: {exc!r}")
            if not (dest / target).exists():
                return ToolResult(ok=False, error=f"refused: {target!r} does not exist in the repo")
            preexec = _apply_rlimits(self._config.test_cpu_seconds, self._config.test_memory_mb * 1024 * 1024) if resource else None
            try:
                # Off the event loop. This `subprocess.run` used to sit
                # directly in the coroutine, and for the whole pytest run
                # -- 272s measured live, 2026-09-10 -- the Kernel's loop
                # did not turn: no heartbeat, no bus, no REPL, a 281s
                # hole in `metrics:history`. It also meant the
                # execution service's own `wait_for` could never fire on
                # a host run (the loop it needed was the one frozen),
                # which hid that its 60s default was the real bound on
                # every tool; see `timeout_s` below.
                # Blocking on purpose: `_run_isolated` already runs on a
                # worker thread (`run` hands it to `asyncio.to_thread`).
                # Two observers fixed the frozen loop the same afternoon,
                # one by threading this call and one by threading the
                # whole method; merged, the inner `await` sat inside a
                # plain `def`.
                completed = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                     *pytest_parallel_args(dest / target), target],
                    capture_output=True, text=True,
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
            # Exit 4 is pytest's *usage* error, which is what a
            # non-Python target produces ("file or directory not found"
            # is exit 4, not 5). Live-caught 2026-09-09, second 95120
            # trial: told to run its tests, Sim called `run_tests
            # docs/games/real_estate_95120_live.html`, got exit 4, read
            # it as a failing suite, and the task blocked with a
            # correct, real-data page sitting uncommitted. A target that
            # is not Python has no tests *by construction* -- that is the
            # same honest "nothing was run" as exit 5, not a failure. The
            # hint names the call that would actually check the change.
            not_python = not (target == "tests" or target.endswith(".py") or (dest / target).is_dir())
            usage_error = completed.returncode == _PYTEST_USAGE_ERROR and not_python
            no_tests = completed.returncode == _PYTEST_NO_TESTS_COLLECTED or usage_error
            ok = completed.returncode == 0 or no_tests
            # Parsed from the WHOLE stdout, before `[-cap:]` and before
            # orchestration's own 2000-char head cut, and prepended so it
            # rides at the head where neither cut can reach it. pytest
            # prints the failing node ids only in its short summary, at
            # the very end; for any run longer than the cut, "which tests
            # failed" reached neither the model nor verification -- both
            # got the top of a traceback and the word "failed". See
            # `contracts/pytestfailures.py`.
            failing = failing_nodeids(completed.stdout) if not ok else ()
            output = completed.stdout[-cap:]
            # The count is pytest's own, not `len(failing)`: a node id
            # this module cannot parse out of the summary (one with a
            # space in a parameter, say) would otherwise shorten the
            # list silently, and a short list reads as "the rest of the
            # suite is somebody else's problem". Disagreeing counts make
            # the marker unattributable instead, which is the honest
            # answer to a list that is missing something.
            marker = marker_for(completed.stdout) if not ok else ""
            if marker:
                output = f"{marker}\n{output}"
            if no_tests:
                output = (output + "\n\n[no tests cover this target yet -- nothing was run]").strip()
            if usage_error:
                output += (
                    "\n[pytest only collects Python tests, and this target is not Python. "
                    "To check a change like this against the suite, call run_tests with no target.]"
                )
            return ToolResult(
                ok=ok, output=output,
                error=None if ok else f"exit_code={completed.returncode}",
                metadata={"failing_nodeids": list(failing),
                          "stderr": completed.stderr[-cap:], "exit_code": completed.returncode,
                          "no_tests_collected": no_tests,
                          "duration_s": time.monotonic() - start},
            )

    def _run_in_container(self, checkout: Path, inner: str, manifest: ContainerCheckout, *,
                          timeout: float, start: float) -> ToolResult:
        """Run `inner` (a path inside `checkout`) with the project's own
        test command, inside the project's own container.

        The checkout is somebody else's project whose dependencies live
        only in its image (`contracts/checkout.py`). What Sim changed --
        committed or not -- is carried in as a diff against the manifest's
        base commit and applied to the image's pristine `/testbed`, the
        same way the scorer does it; the image's own environment prelude
        runs; then its own test command with Sim's target. Nothing here
        can touch the checkout on the host or the image itself: the
        container is thrown away.
        """
        cap = self._config.test_output_max_chars
        docker = shutil.which("docker")
        if not docker:
            return ToolResult(ok=False, error=(
                f"refused: {inner!r} is inside a checkout whose tests run in a container, "
                f"and Docker is not installed on this machine"))
        patch, problem = _checkout_patch(checkout, manifest.diff_base)
        if problem:
            return ToolResult(ok=False, error=f"could not read the checkout's changes: {problem}")
        target = django_label(inner) if manifest.target_style == TARGET_DJANGO_LABEL else inner
        with tempfile.TemporaryDirectory(prefix="simorgh-checkout-tests-") as raw:
            stage = Path(raw)
            # An untouched checkout is an EMPTY file, not "\n": the
            # script's `[ -s ]` guard counts bytes, one newline is a
            # byte, and `git apply` then rejects the "patch" -- so a
            # baseline run before any edit answered "the checkout's
            # changes do not apply to the project's pristine tree" for
            # a tree that WAS pristine (measured against the real
            # django image, 2026-09-10; astropy never showed it because
            # its image's tree already differs from its base commit).
            (stage / "patch.diff").write_text(patch if not patch or patch.endswith("\n") else patch + "\n")
            script = "\n".join([
                "set -o pipefail",
                manifest.setup.rstrip(),
                f"cd {manifest.workdir}",
                # Empty when the checkout is untouched: still a real run.
                "if [ -s /eval/patch.diff ]; then git apply -v /eval/patch.diff "
                "|| patch --batch --fuzz=5 -p1 -i /eval/patch.diff "
                "|| { echo 'SIMORGH_PATCH_FAILED'; exit 90; }; fi",
                ": '>>>>> Start Test Output'",
                f"{manifest.test_command} {target}",
                "",
            ])
            (stage / "run.sh").write_text(script)
            args = [docker, "run", "--rm"]
            if manifest.platform:
                args += ["--platform", manifest.platform]
            args += ["-v", f"{stage}:/eval:ro", manifest.image, "bash", "/eval/run.sh"]
            code, raw_out = _docker_run(args, timeout=timeout)
        duration = time.monotonic() - start
        out = strip_ansi(raw_out)
        marker_start = out.find(">>>>> Start Test Output")
        test_run = out[marker_start:] if marker_start >= 0 else out
        where = container_run_line(inner, manifest.image)
        if code == 124:
            return ToolResult(ok=False, output=test_run[-cap:], error="timeout",
                              metadata={"duration_s": duration, "container": manifest.image})
        if "SIMORGH_PATCH_FAILED" in out:
            return ToolResult(ok=False, error=(
                "the checkout's changes do not apply to the project's pristine tree -- "
                "the diff is malformed or edits files the project does not have"),
                output=out[-cap:], metadata={"duration_s": duration, "container": manifest.image})
        no_tests = code == _PYTEST_NO_TESTS_COLLECTED
        ok = code == 0 or no_tests
        failing = failing_nodeids(test_run) if not ok else ()
        output = f"{where}\n{test_run[-cap:]}"
        marker = marker_for(test_run) if not ok else ""
        if marker:
            output = f"{marker}\n{output}"
        if no_tests:
            output = (output + "\n\n[no tests cover this target yet -- nothing was run]").strip()
        return ToolResult(
            ok=ok, output=output, error=None if ok else f"exit_code={code}",
            metadata={"failing_nodeids": list(failing), "exit_code": code,
                      "no_tests_collected": no_tests, "duration_s": duration,
                      "container": manifest.image, "target": target},
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


#: Lines that are the model talking, not file content. A marker payload
#: runs to the end of the reply, so anything the model says after its
#: content lands inside the file.
_TRANSCRIPT_LINE = re.compile(r"^\s*\[(system|assistant|user|tool|info)\]", re.M | re.I)


def _transcript_tail(code: str) -> str | None:
    """The first line of narration found inside file content, or None.

    `_python_syntax_problem` has caught this for `.py` since 2026-09-07,
    where an unparseable file made it obvious. Everything else was
    written verbatim: an observer watched `workspace/domains.csv` be
    written as six real CSV rows followed by twenty lines of the model's
    own chat, including "[system] Result: written workspace/domains.csv
    (5 data rows + header)." The tool said `ok=True`, verification
    passed, and the final answer described a clean six-line file
    (2026-09-10).

    Deliberately narrow: a transcript prefix at the start of a line
    appears nowhere in this repository's tracked content, so this
    refuses what is unambiguous and leaves prose alone."""
    found = _TRANSCRIPT_LINE.search(code or "")
    if found is None:
        return None
    line = (code[found.start():].splitlines() or [""])[0]
    return line.strip()[:120]


def _write_scoped_file(config: Config, subject: str, code: str, *, write_scopes: tuple[str, ...],
                       root: Path | None = None) -> ToolResult:
    """Shared body of `apply_source_patch`/`apply_skill`: write `code` to
    `subject`, refusing anything outside `write_scopes` -- a tool-level
    scope re-check independent of Guardian's own (v1's "two boundaries,
    not one")."""
    subject = subject.replace("\\", "/")
    if ".." in Path(subject).parts or not pathsafety.in_write_scope(subject, write_scopes=write_scopes):
        # Name them. A bare "outside the writable scope" taught the
        # model nothing, and on 2026-09-09 it guessed the scopes wrong
        # in the other direction -- believing only src/ and simorgh/
        # were writable, it routed a perfectly legal docs/ write through
        # run_shell, the broadest tool it has, rather than ask.
        return ToolResult(
            ok=False,
            error=f"refused: {subject!r} is outside the writable scope ({', '.join(write_scopes)})")
    base = (root or config.repo_root).resolve()
    target = (base / subject).resolve()
    scope_ok = any((base / s).resolve() in target.parents or (base / s).resolve() == target.parent
                    for s in write_scopes)
    if not scope_ok:
        return ToolResult(
            ok=False,
            error=f"refused: {subject!r} resolves outside the writable scope ({', '.join(write_scopes)})")
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
    narration = _transcript_tail(code)
    if narration is not None:
        return ToolResult(
            ok=False,
            error=(f"refused: the content for {subject} contains a line of this conversation "
                   f"rather than file content -- {narration!r}. A marker's payload runs to the end "
                   f"of your reply, so end the reply with the file and say nothing after it."))
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
                f"refused: the new content for {subject} drops {lost} -- apply_source_patch "
                f"replaces the whole file.\n"
                # Naming the right tool, not just the wrong outcome. The
                # refusal used to say "read it all and send it back
                # complete", which is the expensive way and the one that
                # truncates again on a long file -- so a run would read,
                # rewrite, get refused, and read again until its budget
                # was gone (live, 2026-09-09).
                f"Use REPLACE_IN_FILE instead: it changes just the part you name, so nothing "
                f"else can be lost.\n"
                f"  REPLACE_IN_FILE: {subject}\n"
                f"  <<<<<<< SEARCH\n  (the exact lines to change)\n  =======\n"
                f"  (what to put there)\n  >>>>>>> REPLACE\n"
                "If you really do mean to replace the whole file with something much shorter, "
                "say so and send it again."
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
        return _write_scoped_file(self._config, args["subject"], args["code"], write_scopes=self._config.write_scopes_source,
                                  root=tool_root(self._config, ctx, args["subject"]))


class StartTaskTool:
    """Hand a build off to a real task, when a chat turn is the wrong
    shape for it.

    A chat turn does not resume. It gets a step budget, spends it, and
    if the work is unfinished the next message starts again from
    nothing -- which is why "rebuild the voxel game" was attempted three
    times on 2026-09-09 and each attempt rewrote the file from scratch.
    A task is the opposite: it carries its own budget, and when it
    exhausts it the work is re-offered with everything it had already
    done intact (`orchestration/session.py::CONTINUATION_REASON`).

    All the machinery for that existed. What was missing was any way to
    get from "make me a Minecraft game" to a task without the person
    knowing to type `improve ... steps=40` instead. The model is the
    right judge of which it is -- it has the request in front of it --
    so it gets a tool rather than the Interface getting a keyword
    classifier that would call a poem a build.

    Refused from inside a task on purpose. Decomposition is Planning's
    job and it already does it; a task that could spawn tasks is how a
    quiet afternoon becomes a fork bomb.
    """

    name = "start_task"
    description = (
        "Turn the current request into a background task with its own step budget, for work "
        "too big to finish in one reply -- building an app, a long document, anything needing "
        "many edits. Unlike a chat turn, a task resumes where it left off instead of starting "
        "over. Say what you have started and that `tasks` shows progress."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["goal"],
        "properties": {
            "goal": {"type": "string"},
            "subject": {"type": "string", "description": "the file it will mostly write"},
            "steps": {"type": "integer"},
            "kind": {"type": "string", "enum": ["patch", "research", "project"]},
        },
    }

    #: A task cannot ask for an unbounded budget. High enough for a real
    #: build, low enough that a misjudged request cannot spend an
    #: afternoon of provider quota before anyone looks.
    MAX_STEPS = 120
    DEFAULT_STEPS = 40

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        goal = " ".join(str(args.get("goal") or "").split())
        if not goal:
            return ToolResult(ok=False, error="refused: say what the task is for")
        # A chat turn is a session with a task id too (its percept's
        # session id). Its kind rides in the scope; a chat may start
        # work, a task may not. Before 2026-09-11 Execution passed no
        # task id at all, so this refused nothing; the day it started
        # passing one, this refused every chat.
        kind = str((ctx.scope or {}).get("kind") or "")
        if ctx.task_id and kind != "chat":
            return ToolResult(
                ok=False,
                error=("refused: this is already a task, and a task that starts tasks is how a "
                       "quiet afternoon becomes a fork bomb. Break the work down in this task, "
                       "or let Planning decompose it."))
        if ctx.bus is None:
            return ToolResult(ok=False,
                              error="refused: starting a task needs the bus, which this session "
                                    "has not got")

        try:
            steps = int(args.get("steps") or self.DEFAULT_STEPS)
        except (TypeError, ValueError):
            steps = self.DEFAULT_STEPS
        steps = max(5, min(steps, self.MAX_STEPS))
        kind = str(args.get("kind") or "patch").strip().lower()
        if kind not in ("patch", "research", "project"):
            kind = "patch"

        # "assistant", not "human": the person said something and the
        # model decided it was a task. That decision is Sim's, so the
        # task is Sim's -- `auto off` holds it, the backlog cap counts
        # it, and it ranks below what a person asked for by name. The
        # creator's voice turn "Benchmark" -- one word, possibly
        # misheard -- became a 90-step task that went and fetched the
        # upstream fix for a benchmark case, with autonomy off
        # (2026-09-11), because a task started from a chat inherited the
        # chat's `human` origin and the switch never saw it.
        payload = {"kind": kind, "description": goal, "origin": "assistant", "mode": "execute",
                   "max_steps": steps}
        subject = str(args.get("subject") or "").strip()
        if subject:
            payload["subject"] = subject

        from simorgh.contracts import topics as _topics
        from simorgh.contracts.envelope import Message as _Message

        try:
            reply = await ctx.bus.request(
                _Message.new(_topics.TASK_CREATE, source="execution", payload=payload),
                timeout=10.0)
        except Exception as exc:  # noqa: BLE001 -- a failed handoff is a result, not a crash
            return ToolResult(ok=False, error=f"could not start the task: {exc!r}")

        answer = getattr(reply, "payload", {}) or {}
        task_id = str(answer.get("task_id") or "")
        if not task_id:
            return ToolResult(ok=False, error="the task was not created (no id came back)")
        existing = answer.get("deduplicated_against")
        if existing:
            return ToolResult(
                ok=True,
                output=(f"that is already task {existing} -- it is on the backlog rather than "
                        f"being started twice. `tasks` shows it."),
                metadata={"task_id": existing, "deduplicated": True})
        return ToolResult(
            ok=True,
            output=(f"started task {task_id} with {steps} steps: {goal}\n"
                    f"It runs in the background and picks up where it leaves off, so it will not "
                    f"start over the way a chat reply does. `tasks` shows progress; "
                    f"`cancel {task_id}` stops it."),
            side_effects=(f"task {task_id} created",),
            metadata={"task_id": task_id, "steps": steps, "kind": kind})


class ReplaceInFileTool:
    """Change PART of a file, without re-sending the whole thing.

    Until this existed, `apply_source_patch` was the only way to change
    a file and it replaces the file entirely -- so altering one line of
    a 150-line document meant re-emitting all 150 lines. A chat turn has
    an output budget of a couple of thousand tokens, and the file is
    larger than that, so each "edit" wrote a truncated copy and the file
    got shorter every time.

    Live-caught 2026-09-09, rebuilding a voxel game: 147 lines became
    131, then 129, then 76, then 54, each write a sincere attempt at the
    whole file that ran out of room part-way. The content-loss guard
    caught one of the steps and the model simply routed around it with
    smaller files. No amount of prompting fixes that; the tool was
    asking for something the model could not deliver.

    The block format is the familiar one, and the tool parses it itself
    so the marker layer stays a two-part `(path, code)`:

        REPLACE_IN_FILE: workspace/midcraft.html
        <<<<<<< SEARCH
        const SIZE = 16;
        =======
        const SIZE = 32;
        >>>>>>> REPLACE

    The marker shape is the one this codebase already uses
    (`cognition/parser.py`'s own SEARCH/REPLACE regex) and the one every
    model has seen thousands of times in real merge conflicts -- not a
    bespoke format invented here.

    **The text to search for must appear exactly once.** Not once-or-more:
    replacing the first of three identical lines is a coin flip, and the
    two-thirds of the time it guesses wrong the damage is silent. Zero
    matches and several matches are both refusals that say which, so the
    next attempt can add surrounding context rather than guess again.
    """

    name = "replace_in_file"
    description = (
        "Change part of an existing file by finding an exact piece of text and replacing it. "
        "Use this instead of apply_source_patch whenever the file already exists and you are "
        "changing some of it -- apply_source_patch replaces the whole file, so on anything "
        "long it will truncate and destroy the rest."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["path", "code"],
        "properties": {"path": {"type": "string"}, "code": {"type": "string"}},
    }

    def __init__(self, config: Config) -> None:
        self._config = config

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        subject = str(args.get("path") or "").strip().replace("\\", "/")
        if not subject:
            return ToolResult(ok=False, error="refused: name the file to change")
        blocks, problem = parse_replace_blocks(str(args.get("code") or ""))
        if problem:
            return ToolResult(ok=False, error=f"refused: {problem}")

        root = tool_root(self._config, ctx, subject)
        content, refusal = pathsafety.read_source(root, subject, readable_roots=self._config.readable_roots)
        if refusal:
            return ToolResult(ok=False, error=refusal)

        updated = content
        applied = []
        for index, (find, replace) in enumerate(blocks, start=1):
            count = updated.count(find)
            # Whether the EARLIER blocks were fine is the most useful
            # thing this refusal can say. Without it the model resends
            # the whole set blind and gets refused on the same block
            # again -- watched twice in a row on 2026-09-09, six steps
            # spent re-reading a file whose first block had matched
            # perfectly both times.
            good = (f" Blocks 1-{index - 1} matched and can be sent again unchanged;"
                    f" only block {index} needs fixing." if index > 1 else "")
            if count == 0:
                return ToolResult(
                    ok=False,
                    error=(f"refused: block {index}'s SEARCH text is not in {subject}. Nothing "
                           f"was changed.{good} READ_FILE the part you mean to change and copy "
                           f"the text exactly, including its indentation and any blank lines."))
            if count > 1:
                return ToolResult(
                    ok=False,
                    error=(f"refused: block {index}'s SEARCH text appears {count} times in "
                           f"{subject}, so which one you mean is a guess. Nothing was "
                           f"changed.{good} Add a line or two either side to make it unique."))
            updated = updated.replace(find, replace, 1)
            applied.append((find, replace))

        if updated == content:
            # Saying "written" when nothing moved is the failure this
            # project keeps calling out.
            return ToolResult(ok=True, output=f"{subject} already read that way; nothing changed",
                              metadata={"changed": False, "blocks": len(blocks)})

        result = _write_scoped_file(self._config, subject, updated,
                                     write_scopes=self._config.write_scopes_source, root=root)
        if not result.ok:
            return result
        before = len(content.splitlines())
        after = len(updated.splitlines())
        delta = f"{after - before:+d} lines" if after != before else "same length"
        return ToolResult(
            ok=True,
            output=f"{subject}: {len(applied)} change(s) applied, {delta} ({after} lines now)",
            side_effects=result.side_effects,
            metadata={"changed": True, "blocks": len(applied), "lines_before": before,
                      "lines_after": after})


_FIND_MARK = "<<<<<<< SEARCH"
_SPLIT_MARK = "======="
_REPLACE_MARK = ">>>>>>> REPLACE"


def parse_replace_blocks(text: str) -> tuple[list[tuple[str, str]], str]:
    """`(blocks, problem)`. One or more SEARCH/REPLACE blocks.

    Tolerant about the markers themselves -- a model that writes seven
    angle brackets instead of eight has not made a meaningful mistake --
    and strict about the structure, because a half-parsed block would
    write something nobody asked for.
    """
    text = (text or "").strip("\n")
    if not text.strip():
        return [], "no SEARCH/REPLACE block given"
    lines = text.split("\n")
    blocks: list[tuple[str, str]] = []
    find: list[str] | None = None
    replace: list[str] | None = None
    for line in lines:
        bare = line.strip()
        if bare.startswith("<<<<<<<"):
            if find is not None:
                return [], "a second SEARCH opened before the first was closed"
            find, replace = [], None
            continue
        if find is not None and replace is None and bare.startswith("=======") and len(bare) >= 7:
            replace = []
            continue
        if bare.startswith(">>>>>>>"):
            if find is None or replace is None:
                return [], "a REPLACE end marker with no SEARCH before it"
            blocks.append(("\n".join(find), "\n".join(replace)))
            find, replace = None, None
            continue
        if replace is not None:
            replace.append(line)
        elif find is not None:
            find.append(line)
    if find is not None:
        return [], "a SEARCH block was never closed with >>>>>>> REPLACE"
    if not blocks:
        return [], (
            "no SEARCH/REPLACE block found. The shape is:\n"
            f"{_FIND_MARK}\nthe exact text to find\n{_SPLIT_MARK}\n"
            f"what to put there instead\n{_REPLACE_MARK}")
    for index, (find_text, _) in enumerate(blocks, start=1):
        if not find_text.strip():
            return [], f"block {index}'s SEARCH text is empty; it has to name what to replace"
    return blocks, ""


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
        return _write_scoped_file(self._config, args["subject"], args["code"], write_scopes=self._config.write_scopes_skills,
                                  root=tool_root(self._config, ctx, args["subject"]))


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
        root = tool_root(self._config, ctx, path)
        # A path inside a nested repository (a materialised SWE-bench
        # checkout under `workspace/`) is committed THERE: from here it
        # is gitignored and `status` says nothing to commit.
        nested = nested_git_root(root, path)
        if nested is not None:
            root, path = nested
        run = lambda cmd: subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )

        # `git diff --quiet HEAD` alone misses brand-new untracked files
        # (they're outside what `diff` compares against HEAD at all), so
        # the pre-check uses `status --porcelain` instead, which reports
        # untracked/staged/unstaged changes uniformly.
        status = await asyncio.to_thread(run, ["git", "status", "--porcelain", "--", path])
        head = await asyncio.to_thread(run, ["git", "rev-parse", "HEAD"])
        head_sha = head.stdout.strip() if head.returncode == 0 else ""
        if not status.stdout.strip():
            path_sha = await asyncio.to_thread(run, ["git", "hash-object", str(root / path)])
            return ToolResult(
                ok=False, error="nothing_to_commit",
                metadata={"head_sha": head_sha, "path_sha": path_sha.stdout.strip() if path_sha.returncode == 0 else ""},
            )

        add = await asyncio.to_thread(run, ["git", "add", "--", path])
        if add.returncode != 0:
            return ToolResult(ok=False, error=f"git add failed: {add.stderr.strip()}")
        commit = await asyncio.to_thread(run, [
            "git", "-c", f"user.name={_SIM_GIT_AUTHOR_NAME}", "-c", f"user.email={_SIM_GIT_AUTHOR_EMAIL}",
            "commit", "-m", message, "--", path,
        ])
        if commit.returncode != 0:
            detail = commit.stderr.strip() or commit.stdout.strip()
            return ToolResult(ok=False, error=f"git commit failed: {detail}")
        new_head = await asyncio.to_thread(run, ["git", "rev-parse", "HEAD"])
        return ToolResult(
            ok=True, output=commit.stdout.strip(), side_effects=(f"git_commit:{args['path']}",),
            metadata={"commit": new_head.stdout.strip() if new_head.returncode == 0 else "",
                      "repository": str(root) if nested is not None else ""},
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
            return ToolResult(
                ok=False,
                error=f"refused: {subject!r} is outside the writable scope ({', '.join(scopes)})")
        root = tool_root(self._config, ctx, subject)
        nested = nested_git_root(root, subject)
        if nested is not None:
            root, subject = nested
        run = lambda cmd: subprocess.run(  # noqa: E731
            cmd, cwd=root, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )
        known = await asyncio.to_thread(run, ["git", "ls-files", "--error-unmatch", subject])
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
        result = await asyncio.to_thread(run, ["git", "checkout", "--", subject])
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
        root = tool_root(self._config, ctx)
        run = lambda cmd: subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )
        result = await asyncio.to_thread(run, [
            "git", "-c", f"user.name={_SIM_GIT_AUTHOR_NAME}", "-c", f"user.email={_SIM_GIT_AUTHOR_EMAIL}",
            "revert", "--no-edit", "HEAD",
        ])
        if result.returncode != 0:
            return ToolResult(ok=False, error=f"git revert failed: {result.stderr.strip() or result.stdout.strip()}")
        new_head = await asyncio.to_thread(run, ["git", "rev-parse", "HEAD"])
        return ToolResult(
            ok=True, output=result.stdout.strip(), side_effects=("git_revert",),
            metadata={"commit": new_head.stdout.strip() if new_head.returncode == 0 else ""},
        )


_SKILL_DRIVER = """import sys, os, json, asyncio, inspect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _skill_module as _skill
_args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
if not hasattr(_skill, "run"):
    raise SystemExit("skill module has no run() entrypoint")
_result = _skill.run(**_args)
# A skill drafted as `async def run(...)` (skill_marker_arg_key already
# recognizes ast.AsyncFunctionDef when inferring the marker arg, so the
# model is never told this shape is unsupported) returns a coroutine here
# rather than the skill's real return value. Un-awaited, that coroutine
# used to reach json.dumps() and blow up with "Object of type coroutine is
# not JSON serializable" plus a "coroutine 'run' was never awaited"
# RuntimeWarning on every single invocation -- live-caught, 2026-09-08.
if inspect.isawaitable(_result):
    _result = asyncio.run(_result)
print(_result if isinstance(_result, str) else json.dumps(_result))
"""


def skill_marker_arg_key(source: str) -> str | None:
    """The keyword `SkillTool.run` should be called with for a marker-shaped
    (single-string) call -- the skill's own `run()` function's first
    parameter name, e.g. `def run(path):` -> `"path"`.

    Static (AST-only, no exec) on purpose: this runs at registration time,
    outside the sandboxed subprocess, so it must never execute a single
    line of the skill's own code -- `inspect.signature` would require
    importing the module first. Returns `None` when the source doesn't
    parse or has no top-level `run`/`async def run`, leaving the caller to
    fall back to the historical `"text"` default.

    Live-caught (audit, 2026-09-08): `orchestration/tools.py::
    register_tool_policy` hardcoded every skill's marker arg to `"text"`
    regardless of what the skill's `run()` actually declared -- a skill
    written as `def run(path):` was called with `text=...` and raised
    `TypeError: run() got an unexpected keyword argument 'text'` on every
    single invocation from the marker layer.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            args = node.args
            positional = [*args.posonlyargs, *args.args]
            if positional:
                return positional[0].arg
            if args.kwonlyargs:
                return args.kwonlyargs[0].arg
            return None
    return None


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
        # Threaded through `tool.registered` (Service._load_skill) to
        # `orchestration/tools.py::register_tool_policy`, so a marker-
        # shaped call (`APPLY_SKILL:`-acquired skills are always called
        # this way -- there is no other calling convention this session)
        # lands on the skill's own first parameter name instead of a
        # hardcoded "text".
        self.marker_arg_key = skill_marker_arg_key(source) or "text"

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        timeout = min(ctx.constraints.get("timeout_s", self._config.sandbox_timeout_s), self._config.sandbox_timeout_s)
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="simorgh-skill-") as workdir:
            (Path(workdir) / "_skill_module.py").write_text(self._source)
            driver = Path(workdir) / "run_skill.py"
            driver.write_text(_SKILL_DRIVER)
            preexec = _apply_rlimits(self._config.sandbox_cpu_seconds, self._config.sandbox_memory_mb * 1024 * 1024) if resource else None
            try:
                completed = await asyncio.to_thread(   # off the loop thread, see RunPythonTool
                    subprocess.run,
                    # `cwd` used to be the throwaway `workdir` (a fresh
                    # tempdir with only the driver + module in it), so a
                    # correctly-invoked skill that took a repo-relative
                    # path (e.g. "simorgh/__init__.py") could never open
                    # it -- live-caught, audit 2026-09-08. A skill already
                    # runs as arbitrary Python with no filesystem
                    # confinement beyond the CPU/memory rlimits below (an
                    # absolute path was always writable); running it from
                    # `repo_root` instead only makes the common case --
                    # relative paths -- resolve the way the model expects,
                    # it does not widen what the skill could already reach.
                    [sys.executable, "-I", str(driver), json.dumps(args)], capture_output=True, text=True,
                    cwd=str(self._config.repo_root), env={}, timeout=timeout, preexec_fn=preexec,
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


def builtin_tools(config: Config, *, secrets=None) -> list:
    """`secrets` is the subsystem's scoped secret store. Only the
    account-backed tools use it, and they take the value at call time so
    a rotated credential is picked up without a restart."""
    return [
        ReadFileTool(config), ListDirTool(config), SearchCodeTool(config), SelfMapTool(config),
        RunPythonSandboxedTool(config), RunJsSandboxedTool(config),
        RunTestsTool(config), ApplySourcePatchTool(config), GitCommitTool(config), GitRevertTool(config),
        GitDiscardTool(config),
        ReplaceInFileTool(config), StartTaskTool(config),
        ApplySkillTool(config), WebFetchTool(config), WebSearchTool(config), RenderPageTool(config),
        RealEstateListingsTool(config), GeocodeTool(config), ProposeMcpServerTool(),
        FindPackageTool(config), InstallPackageTool(config), RunScriptTool(config),
        BrowsePageTool(config), RunContainerTool(config), NotifyTool(config),
        # The creator's own documents (execution/knowledge/,
        # domains/01-knowledge.md). Registered whether or not a source is
        # configured: an unconfigured knowledge base answers with what to
        # add, which beats the tool not existing on the day somebody
        # points it at ~/Documents.
        *knowledge_tools(config),
        # Calendar and mail (execution/pim/,
        # domains/02-calendar-mail-tasks.md). Read-only: sending is
        # irreversible and gets a human gate, and a connector that
        # cannot write at all is a stronger guarantee than a policy
        # saying it should not.
        *pim_tools(config, secrets=secrets),
        # Sim's own security posture (execution/security/,
        # domains/04-security-posture.md). Guardian audits the code Sim
        # writes; nothing audited what Sim *is*.
        *security_tools(config, secrets=secrets),
        # The house, through Home Assistant (execution/home/,
        # home-automation-design.md). The acting half only: finding,
        # reading, calling, undoing. The percept bridge and the rules
        # engine are the `home` subsystem, still to be built.
        *home_tools(config, secrets=secrets),
        # What the house costs (execution/energy/) and what it is
        # playing (execution/media/). Both read through the same Home
        # Assistant client the home_* tools use.
        *energy_tools(config, secrets=secrets),
        *media_tools(config, secrets=secrets),
        # The cameras: a Reolink NVR and everything on it (execution/home/cameras.py).
        *cameras_tools(config, secrets=secrets),
        # The Ring cameras, through Ring's cloud (execution/home/ring.py).
        *ring_tools(config, secrets=secrets),
        # Off unless `[execution] shell = true`: the one tool whose blast
        # radius is not bounded by its own arguments (execution/shell.py).
        *((RunShellTool(config),) if getattr(config, "shell", False) else ()),
        # Off unless `[execution] remote = true`: it reaches a machine
        # nothing here can inspect or roll back (execution/remote.py).
        *((RunRemoteTool(config),) if getattr(config, "remote", False) else ()),
    ]
