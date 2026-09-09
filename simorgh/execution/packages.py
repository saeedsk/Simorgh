"""`find_package` and `install_package`: the two tools that turn "I have
no capability for this" into "there is a library for this".

The 2026-09-09 post-mortem in `docs/plans/resourcefulness-toolset.md`:
asked to build a real-estate browser, Sim stopped at "no listings API
is configured" while another agent found `homeharvest` on PyPI and
shipped real data. Three causes; this module addresses the one that is
a missing tool rather than a missing instruction. `run_shell` could
always `pip install` -- but a shell command is unstructured, unaudited,
and the broadest tool in the box. These two are narrow, checked, and
leave a record.

`find_package` is lookup and costs nothing to get wrong.
`install_package` changes the machine and reaches the network, so it is
declared `irreversible` (Guardian gates every call the way it gates
`run_shell`), refuses anything that is not a plain package name, and
appends a line to `simorgh_packages.txt` so a human can see what Sim
installed and why.

The typosquat guard is deliberately crude and deliberately overridable:
a package whose FIRST release is younger than `package_min_age_days`,
or that publishes no homepage at all, needs `allow_new: true` and a
reason. It stops the accident (a hallucinated name that happens to
exist), not a determined attacker -- same bargain as
`DEFAULT_SHELL_REFUSALS`.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config
from .netsafety import FetchRefused, validate_public_http_url

PYPI_URL = "https://pypi.org/pypi/{name}/json"
NPM_URL = "https://registry.npmjs.org/{name}"

# A package name, and nothing else: no URL, no path, no VCS ref, no
# shell metacharacter. `pip install` accepts all of those and each one
# is a way to run code from somewhere nobody reviewed.
_SPEC_RE = re.compile(r"^(?P<name>@?[A-Za-z0-9][A-Za-z0-9._/-]{0,127})(?P<pin>(==|@|>=|~=)[A-Za-z0-9._-]{1,32})?$")
_PACKAGE_JSON_MAX_BYTES = 2_000_000


def parse_spec(spec: str) -> tuple[str, str] | None:
    """`(name, pin)` for a plain package spec, or None if it is anything
    else. A `/` is allowed only as an npm scope separator (`@scope/x`)."""
    spec = (spec or "").strip()
    if not spec or "://" in spec or spec.startswith((".", "/", "-")) or "file:" in spec.lower():
        return None
    match = _SPEC_RE.match(spec)
    if not match:
        return None
    name = match.group("name")
    if "/" in name:
        if not name.startswith("@"):
            return None
        # A scoped name is exactly `@scope/name` -- two non-empty
        # segments, neither a path-traversal component. Without this,
        # `@x/../evil-pkg` matched the regex above (`.` and `/` are
        # both legal name characters) and both pip and npm resolved it
        # to a real local directory instead of a registry lookup: pip
        # ran that directory's setup.py at metadata time -- even under
        # `--dry-run` -- and npm ran its postinstall script, in both
        # cases arbitrary code, not "one plain package name". Confirmed
        # live 2026-09-09 by an observer.
        segments = name[1:].split("/")
        if len(segments) != 2 or any(not s or s in (".", "..") or ".." in s for s in segments):
            return None
    return name, match.group("pin") or ""


def _get_json(opener, url: str, timeout: float) -> dict | None:
    validate_public_http_url(url, allow_private=False)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            return json.loads(response.read(_PACKAGE_JSON_MAX_BYTES).decode("utf-8", "replace"))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def _iso(value: str) -> str:
    return (value or "")[:10]


def pypi_facts(payload: dict) -> dict:
    info = payload.get("info") or {}
    releases = payload.get("releases") or {}
    uploads = [
        f["upload_time_iso_8601"]
        for files in releases.values() for f in (files or [])
        if isinstance(f, dict) and f.get("upload_time_iso_8601")
    ]
    urls = info.get("project_urls") or {}
    return {
        "manager": "pypi",
        "name": info.get("name", ""),
        "summary": (info.get("summary") or "").strip()[:200],
        "version": info.get("version", ""),
        "licence": (info.get("license") or "").strip()[:40],
        "homepage": info.get("home_page") or urls.get("Homepage") or urls.get("Source") or "",
        "first_release": _iso(min(uploads)) if uploads else "",
        "latest_release": _iso(max(uploads)) if uploads else "",
    }


def npm_facts(payload: dict) -> dict:
    latest = ((payload.get("dist-tags") or {}).get("latest")) or ""
    times = payload.get("time") or {}
    versions = payload.get("versions") or {}
    meta = versions.get(latest) or {}
    repository = meta.get("repository") or {}
    return {
        "manager": "npm",
        "name": payload.get("name", ""),
        "summary": (payload.get("description") or "").strip()[:200],
        "version": latest,
        "licence": str(meta.get("license") or "")[:40],
        "homepage": meta.get("homepage") or (repository.get("url") if isinstance(repository, dict) else "") or "",
        "first_release": _iso(times.get("created", "")),
        "latest_release": _iso(times.get(latest, "")),
    }


def render_hits(hits: list[dict]) -> str:
    lines = []
    for hit in hits:
        head = f"{hit['manager']} {hit['name']} {hit['version']}".rstrip()
        dates = f"latest {hit['latest_release'] or '?'}, first {hit['first_release'] or '?'}"
        licence = f" {hit['licence']}" if hit["licence"] else ""
        lines.append(f"{head} ({dates}){licence}\n   {hit['summary'] or '(no summary)'}\n   {hit['homepage'] or '(no homepage)'}")
    return "\n".join(lines)


class FindPackageTool:
    name = "find_package"
    description = "Look up a package on PyPI or npm by exact name: version, age, licence, homepage, summary."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["query"], "properties": {
        "query": {"type": "string"}, "manager": {"type": "string"}}}

    def __init__(self, config: Config, *, opener=None) -> None:
        self._config = config
        self._opener = opener or urllib.request.urlopen

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="refused: an empty package name")
        parsed = parse_spec(query)
        if parsed is None:
            return ToolResult(ok=False, error=f"refused: {query!r} is not a plain package name")
        name = parsed[0]
        manager = str(args.get("manager") or "any").strip().lower()
        hits = await asyncio.to_thread(self._lookup, name, manager)
        if not hits:
            return ToolResult(
                ok=True, output=f"no package named {name!r} on {manager if manager != 'any' else 'PyPI or npm'}",
                metadata={"hits": [], "query": name},
            )
        return ToolResult(ok=True, output=render_hits(hits), metadata={"hits": hits, "query": name})

    def _lookup(self, name: str, manager: str) -> list[dict]:
        timeout = self._config.package_lookup_timeout_s
        hits = []
        # A scoped name (`@scope/x`) exists only on npm; never send it to PyPI.
        if manager in ("any", "pypi") and not name.startswith("@"):
            payload = _get_json(self._opener, PYPI_URL.format(name=urllib.parse.quote(name)), timeout)
            if payload:
                hits.append(pypi_facts(payload))
        if manager in ("any", "npm"):
            payload = _get_json(self._opener, NPM_URL.format(name=urllib.parse.quote(name, safe="@/")), timeout)
            if payload:
                hits.append(npm_facts(payload))
        return hits


class InstallPackageTool:
    name = "install_package"
    description = (
        "Install one package with pip or npm so you can use it. Irreversible (it changes this "
        "machine): Guardian gates every call, and the install is recorded."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {"type": "object", "required": ["manager", "spec"], "properties": {
        "manager": {"type": "string"}, "spec": {"type": "string"},
        "allow_new": {"type": "boolean"}, "reason": {"type": "string"}}}

    def __init__(self, config: Config, *, opener=None, runner=None, clock=None) -> None:
        self._config = config
        self._finder = FindPackageTool(config, opener=opener)
        self._runner = runner or subprocess.run
        self._clock = clock or time.time

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        manager = str(args.get("manager") or "").strip().lower()
        if manager not in ("pip", "npm"):
            return ToolResult(ok=False, error="refused: manager must be 'pip' or 'npm'")
        parsed = parse_spec(str(args.get("spec") or ""))
        if parsed is None:
            return ToolResult(
                ok=False,
                error="refused: spec must be a plain package name (optionally pinned) -- "
                      "no URL, path, VCS ref or local file",
            )
        name, pin = parsed
        if any(re.search(pattern, name) for pattern in self._config.package_denylist):
            return ToolResult(ok=False, error=f"refused: {name!r} is on the package denylist")

        used, cap = self._installs_today(), self._config.max_installs_per_day
        if used >= cap:
            return ToolResult(ok=False, error=f"refused: {used}/{cap} installs already today")

        allow_new = bool(args.get("allow_new"))
        if not allow_new:
            refusal = await asyncio.to_thread(self._vet, name, manager)
            if refusal:
                return ToolResult(ok=False, error=refusal)

        spec = f"{name}{pin}"
        completed = await asyncio.to_thread(self._install, manager, spec)
        if completed is None:
            return ToolResult(ok=False, error="timeout")
        cap_chars = self._config.test_output_max_chars
        if completed.returncode != 0:
            return ToolResult(
                ok=False, error=f"install failed (exit {completed.returncode})",
                output=(completed.stdout or "")[-cap_chars:],
                metadata={"stderr": (completed.stderr or "")[-cap_chars:]},
            )
        self._record(manager, spec, ctx, str(args.get("reason") or ""))
        return ToolResult(
            ok=True, output=(completed.stdout or "")[-cap_chars:] + f"\n\ninstalled {spec} with {manager}",
            metadata={"manager": manager, "spec": spec, "name": name},
        )

    def _vet(self, name: str, manager: str) -> str | None:
        """Empty when the package looks real. A lookup that cannot run at
        all is a refusal, not a pass: "I could not check" must never read
        as "I checked and it was fine"."""
        hits = self._finder._lookup(name, "npm" if manager == "npm" else "pypi")
        if not hits:
            return (f"refused: could not find {name!r} on {manager}'s registry to check it. "
                    "If you are sure of the name, retry with allow_new: true and say why")
        hit = hits[0]
        if not hit.get("homepage"):
            return (f"refused: {name!r} publishes no homepage or repository, which is unusual for a real "
                    "package. Retry with allow_new: true and say why if you are sure")
        first = hit.get("first_release") or ""
        age_days = None
        if first:
            try:
                age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(first).replace(tzinfo=timezone.utc)).days
            except ValueError:
                age_days = None
        # A missing or unparseable first-release date is the same shape as
        # a lookup that could not run: "I don't know its age" must refuse,
        # not silently pass as if the package were vetted and found old
        # enough. Without this, a registry response with no upload-time
        # metadata at all (or a malformed one) skipped the age check
        # entirely and installed on the first try -- confirmed live
        # 2026-09-09 by an observer.
        if age_days is None:
            return (f"refused: could not determine {name!r}'s first-release date to check its age "
                    f"(the registry gave no usable upload-time data). Retry with allow_new: true and "
                    "say why if you are sure")
        if age_days < self._config.package_min_age_days:
            return (f"refused: {name!r} first published {first} ({age_days} days ago), under the "
                    f"{self._config.package_min_age_days}-day floor -- a brand-new package with a "
                    "plausible name is the shape a typosquat takes. Retry with allow_new: true and say why")
        return None

    def _install(self, manager: str, spec: str):
        command = (
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", spec]
            if manager == "pip" else ["npm", "install", "-g", spec]
        )
        try:
            return self._runner(
                command, capture_output=True, text=True,
                timeout=self._config.package_install_timeout_s, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return None
        except OSError as exc:
            class _Failed:
                returncode, stdout, stderr = 127, "", f"could not run {manager}: {exc!r}"
            return _Failed()

    def _log_path(self) -> Path:
        return self._config.repo_root / self._config.package_log

    def _installs_today(self) -> int:
        today = datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat()
        try:
            lines = self._log_path().read_text().splitlines()
        except OSError:
            return 0
        return sum(1 for line in lines if line.startswith(today))

    def _record(self, manager: str, spec: str, ctx: ToolContext, reason: str) -> None:
        stamp = datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(timespec="seconds")
        task = getattr(ctx, "task_id", None) or "-"
        line = f"{stamp} {manager} {spec} task={task} reason={' '.join((reason or '-').split())[:160]}\n"
        try:
            with self._log_path().open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass  # the install really happened; failing to log it must not undo that
