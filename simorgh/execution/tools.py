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
from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import ToolContext, ToolResult

from . import pathsafety
from .config import Config
from .htmltext import html_to_text, looks_like_html
from .netsafety import FetchRefused, validate_public_http_url
from .doctext import document_to_text
from .geocode import GeocodeTool
from .packages import FindPackageTool, InstallPackageTool
from .pdftext import looks_like_pdf, pdf_to_text
from .realestate import RealEstateListingsTool
from .script import RunScriptTool
from .knowledge.tools import knowledge_tools
from .pim.tools import pim_tools
from .home.tools import home_tools
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
                self._config.repo_root, path, readable_roots=self._config.readable_roots)
        else:
            # Slice the REAL file, never a pre-capped string: that was the
            # bug that made 61% of this very module unreachable.
            content = await asyncio.to_thread(
                pathsafety.safe_read_lines,
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


def _rg_line_is_credential(line: str) -> bool:
    """`ripgrep` output is `path:lineno:text`; check the path prefix
    against the same credential-name filter `resolve_safe_path` (and
    `read_file`) already enforce, so `search_code` cannot grep a
    `.env`/`credentials.json`/etc. that a direct `read_file` on the same
    path would refuse. `rg`'s own default hidden-file skip masked the
    dotfile case (`.env`) by accident but never covered a non-hidden
    name like `credentials.json` -- found live, 2026-09-08."""
    path_part = line.split(":", 1)[0]
    return pathsafety.looks_like_credential_path(Path(path_part).parts)


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
            return ToolResult(ok=True, output=_no_match_note(self._config),
                              metadata={"matches": 0, "files_scanned": 0, "via": "ripgrep"})
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

        lines = [
            ln for ln in completed.stdout.splitlines()
            if "__pycache__" not in ln and not _rg_line_is_credential(ln)
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
                if pathsafety.looks_like_credential_path(path.relative_to(root).parts):
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
        if self._config.web_fetch_extract_text and looks_like_html(full_text):
            content, js_shell = html_to_text(full_text, url=url)
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
                completed = subprocess.run(
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
                # `papers/` (109 MB of PDFs) and the observers' scratch
                # area were copied into every isolated test run and no
                # test reads either; the copy is 17 MB without them.
                # NOT "ledger": that pattern would also drop the
                # `simorgh/ledger` package and its tests.
                shutil.copytree(root, dest, ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".git", ".simdata", "*.egg-info", ".pytest_cache",
                    "papers", "scratchpad", ".simorgh",
                ))
            except OSError as exc:
                return ToolResult(ok=False, error=f"could not stage an isolated copy: {exc!r}")
            if not (dest / target).exists():
                return ToolResult(ok=False, error=f"refused: {target!r} does not exist in the repo")
            preexec = _apply_rlimits(self._config.test_cpu_seconds, self._config.test_memory_mb * 1024 * 1024) if resource else None
            try:
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
            output = completed.stdout[-cap:]
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
        # Name them. A bare "outside the writable scope" taught the
        # model nothing, and on 2026-09-09 it guessed the scopes wrong
        # in the other direction -- believing only src/ and simorgh/
        # were writable, it routed a perfectly legal docs/ write through
        # run_shell, the broadest tool it has, rather than ask.
        return ToolResult(
            ok=False,
            error=f"refused: {subject!r} is outside the writable scope ({', '.join(write_scopes)})")
    target = (config.repo_root / subject).resolve()
    scope_ok = any((config.repo_root / s).resolve() in target.parents or (config.repo_root / s).resolve() == target.parent
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
            return ToolResult(
                ok=False,
                error=f"refused: {subject!r} is outside the writable scope ({', '.join(scopes)})")
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
                completed = subprocess.run(
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
        # Off unless `[execution] shell = true`: the one tool whose blast
        # radius is not bounded by its own arguments (execution/shell.py).
        *((RunShellTool(config),) if getattr(config, "shell", False) else ()),
        # Off unless `[execution] remote = true`: it reaches a machine
        # nothing here can inspect or roll back (execution/remote.py).
        *((RunRemoteTool(config),) if getattr(config, "remote", False) else ()),
    ]
