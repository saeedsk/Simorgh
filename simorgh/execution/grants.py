"""Capabilities Sim gives itself, and the boundary around them.

The resourcefulness work of 2026-09-09 ends here. `find_package` finds
a library, `install_package` installs it, `run_script` uses it -- but
using it meant writing a fresh script every time. A *grant* is the
durable version: "this installed callable, or this MCP server, is now
a tool", recorded in a file a human can read and revoke.

This is the one change in that whole effort that widens what Sim can
do to itself, so the boundary is stated here rather than left implicit:

1. **A grant never loosens Guardian.** Every self-granted tool is
   registered `irreversible`, the strictest tier, so `ReversibilityRule`
   gates every single call. Only a human, through `capability promote`,
   can make one `reversible` or `read_only`. `ExternalToolSpec` already
   defaults this way for exactly the same reason (a live incident on
   2026-09-08: an unaudited `os.remove` wrapper ran with no
   escalation); a grant may not override it.
2. **A grant is itself a gated action.** `grant_capability` is an
   `irreversible` tool. Guardian sees the proposal, the denylist reads
   its import path and command, and a denied grant is remembered by
   `ImmunityRule`, so a near-identical retry is refused too.
3. **Sim never edits `simorgh.toml`.** Grants live in their own file.
   The human-written config stays human-written -- the same structural
   boundary `propose_mcp_server` already respects.
4. **The guard rails below are for the accident, not the adversary.**
   A module denylist and a command allowlist stop a model reaching for
   `os:system` or `npx -e '<code>'`. Anything with `run_shell` can
   already do more; this is not a sandbox, and pretending otherwise
   would be the dishonest kind of security. What it does buy is that
   every capability Sim adds is *named, recorded, and revocable*.

A grant is not the same as a skill. A skill is code Sim wrote and can
rewrite; a grant is a door to somebody else's code, which is why it
gets a file, an audit trail, and a revoke command.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

try:  # pragma: no cover -- 3.11+ everywhere this runs
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config
from .external import KINDS, ExternalToolSpec
from .mcp import McpServerConfig

GRANT_KINDS = ("external", "mcp")

# `pkg.module:callable` and nothing else -- no path, no attribute walk,
# no dunder. The callable must start with a LETTER: `pkg:__import__` is
# otherwise a perfectly well-formed import path, and it is the exact
# escape this pattern exists to close (caught by its own test, before
# the first grant was ever made).
_IMPORT_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z][A-Za-z0-9_]*$")
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# npm/PyPI package names an MCP server may be launched from.
_PACKAGE_ARG_RE = re.compile(r"^(@[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+(@[A-Za-z0-9._-]+)?$")
# Commands `propose_mcp_server` already allows; a grant may not widen it.
_ALLOWED_COMMANDS = frozenset({"npx", "uvx", "node", "python", "python3"})
# Anything that turns "run this package" into "run this code".
_FORBIDDEN_ARGS = ("-e", "--eval", "-c", "--command", "-", "--")
_SHELL_METACHARACTERS = set(";|&$`><\n")
# Every self-granted tool carries this prefix, so a grant can never
# occupy (or be mistaken for) a builtin's name.
GRANT_NAME_PREFIX = "x_"


@dataclass(frozen=True)
class Grant:
    id: str
    kind: Literal["external", "mcp"]
    granted_at: str
    granted_by_task: str = "-"
    reason: str = ""
    status: Literal["active", "revoked"] = "active"
    reversibility: str = "irreversible"
    name: str = ""
    # kind="external"
    import_path: str = ""
    adapter: str = "callable"
    # kind="mcp"
    command: str = ""
    args: tuple[str, ...] = ()
    read_only_tools: tuple[str, ...] = ()
    env_keys: tuple[str, ...] = ()
    tools: tuple[str, ...] = field(default_factory=tuple)

    def to_toml(self) -> str:
        def q(value: str) -> str:
            return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

        def arr(values) -> str:
            return "[" + ", ".join(q(v) for v in values) + "]"

        lines = ["[[grants]]"]
        for key in ("id", "kind", "granted_at", "granted_by_task", "reason", "status",
                    "reversibility", "name", "import_path", "adapter", "command"):
            value = getattr(self, key)
            if value:
                lines.append(f"{key} = {q(value)}")
        for key in ("args", "read_only_tools", "env_keys", "tools"):
            values = getattr(self, key)
            if values:
                lines.append(f"{key} = {arr(values)}")
        return "\n".join(lines) + "\n"

    def as_external_spec(self) -> ExternalToolSpec:
        return ExternalToolSpec(
            import_path=self.import_path, kind=self.adapter, name=self.name,
            reversibility=self.reversibility, read_only=self.reversibility == "read_only",
        )

    def as_mcp_config(self, env: dict[str, str] | None = None) -> McpServerConfig:
        return McpServerConfig(
            name=self.name, command=self.command, args=tuple(self.args),
            env=dict(env or {}), read_only_tools=frozenset(self.read_only_tools),
        )


class GrantStore:
    """`grants.toml`: read at boot, appended at runtime, edited by hand
    when a human wants to. Never `simorgh.toml`."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> list[Grant]:
        """Every grant on file. A malformed file yields nothing and is
        never fatal -- the same rule a bad MCP server gets: one bad
        entry must not stop the Kernel booting."""
        if tomllib is None or not self.path.is_file():
            return []
        try:
            data = tomllib.loads(self.path.read_text())
        except (OSError, ValueError):
            return []
        grants = []
        for row in data.get("grants") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            try:
                grants.append(Grant(
                    id=str(row["id"]), kind=str(row.get("kind", "external")),
                    granted_at=str(row.get("granted_at", "")),
                    granted_by_task=str(row.get("granted_by_task", "-")),
                    reason=str(row.get("reason", "")), status=str(row.get("status", "active")),
                    # An edited file cannot loosen the floor by hand-writing
                    # something unknown here; only the two real tiers below
                    # `irreversible` are honoured.
                    reversibility=(str(row.get("reversibility", "irreversible"))
                                   if row.get("reversibility") in ("read_only", "reversible")
                                   else "irreversible"),
                    name=str(row.get("name", "")), import_path=str(row.get("import_path", "")),
                    adapter=str(row.get("adapter", "callable")), command=str(row.get("command", "")),
                    args=tuple(str(a) for a in row.get("args", ())),
                    read_only_tools=tuple(str(a) for a in row.get("read_only_tools", ())),
                    env_keys=tuple(str(a) for a in row.get("env_keys", ())),
                    tools=tuple(str(a) for a in row.get("tools", ())),
                ))
            except (TypeError, ValueError):
                continue
        return grants

    def active(self) -> list[Grant]:
        return [g for g in self.load() if g.status == "active"]

    def append(self, grant: Grant) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = "" if self.path.exists() else (
            "# Capabilities Sim granted itself (execution/grants.py).\n"
            "# Machine-written; safe to read, edit or delete by hand.\n"
            "# `status = \"revoked\"` disables a row without losing the record.\n\n"
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(header + grant.to_toml() + "\n")

    def set_status(self, grant_id: str, status: str) -> Grant | None:
        grants = self.load()
        found = None
        for index, grant in enumerate(grants):
            if grant.id == grant_id:
                found = replace(grant, status=status)
                grants[index] = found
        if found is None:
            return None
        self._rewrite(grants)
        return found

    def set_reversibility(self, grant_id: str, reversibility: str) -> Grant | None:
        grants = self.load()
        found = None
        for index, grant in enumerate(grants):
            if grant.id == grant_id:
                found = replace(grant, reversibility=reversibility)
                grants[index] = found
        if found is None:
            return None
        self._rewrite(grants)
        return found

    def _rewrite(self, grants: list[Grant]) -> None:
        body = (
            "# Capabilities Sim granted itself (execution/grants.py).\n"
            "# Machine-written; safe to read, edit or delete by hand.\n"
            "# `status = \"revoked\"` disables a row without losing the record.\n\n"
            + "\n".join(g.to_toml() for g in grants)
        )
        temp = self.path.with_suffix(".toml.tmp")
        temp.write_text(body)
        temp.replace(self.path)


def validate_external(spec: dict, config: Config) -> str | None:
    """Empty when this external grant may proceed; the refusal otherwise."""
    import_path = str(spec.get("import_path") or "").strip()
    if not _IMPORT_PATH_RE.match(import_path):
        return ("refused: import_path must be `package.module:callable` -- "
                f"got {import_path!r}")
    module_root = import_path.split(":", 1)[0].split(".", 1)[0]
    if module_root in config.grant_import_denylist:
        return (f"refused: {module_root!r} is on the grant denylist -- granting a tool over it "
                "would hand out the machine rather than a library")
    adapter = str(spec.get("adapter") or "callable")
    if adapter not in KINDS:
        return f"refused: adapter must be one of {KINDS}, not {adapter!r}"
    name = str(spec.get("name") or "").strip()
    if name and not _TOOL_NAME_RE.match(name):
        return f"refused: {name!r} is not a valid tool name"
    return None


def validate_mcp(spec: dict) -> str | None:
    """Empty when this MCP grant may proceed; the refusal otherwise."""
    command = str(spec.get("command") or "").strip()
    if command not in _ALLOWED_COMMANDS:
        return f"refused: command must be one of {sorted(_ALLOWED_COMMANDS)}, not {command!r}"
    args = spec.get("args") or []
    if not isinstance(args, (list, tuple)) or not args:
        return "refused: an MCP server needs args naming the package to run"
    for arg in args:
        text = str(arg)
        if text in _FORBIDDEN_ARGS or text.startswith(("-e", "--eval", "-c", "--command")):
            return f"refused: {text!r} turns 'run this package' into 'run this code'"
        if _SHELL_METACHARACTERS & set(text):
            return f"refused: {text!r} contains a shell metacharacter"
        if text.startswith("/") or text.startswith("./") or ".." in text:
            return f"refused: {text!r} is a path, not a package name"
    package_args = [str(a) for a in args if not str(a).startswith("-")]
    if not package_args or not _PACKAGE_ARG_RE.match(package_args[0]):
        return "refused: args must name a package (e.g. `-y @scope/server-name`)"
    for key in spec.get("env_keys") or []:
        if not re.match(r"^[A-Z][A-Z0-9_]*$", str(key)):
            return f"refused: {key!r} is not an environment variable name"
    name = str(spec.get("name") or "").strip()
    if not name or not _TOOL_NAME_RE.match(name):
        return f"refused: an MCP grant needs a short server name, got {name!r}"
    return None


def _server_name_for(package: str) -> str:
    """`@modelcontextprotocol/server-time` -> `time`. The registered
    tools become `mcp_time_<tool>`, which is what the model types."""
    tail = package.rsplit("/", 1)[-1]
    tail = re.sub(r"^mcp[-_]?server[-_]?|^server[-_]?", "", tail)
    tail = re.sub(r"[-_]?mcp[-_]?server$|[-_]?server$", "", tail)
    return re.sub(r"[^a-z0-9_]+", "_", tail.lower()).strip("_") or "server"


def grant_id(clock=None) -> str:
    import uuid

    stamp = datetime.fromtimestamp((clock or time.time)(), timezone.utc).strftime("%Y%m%d")
    return f"g-{stamp}-{uuid.uuid4().hex[:6]}"


def tool_name_for(spec: dict, import_path: str) -> str:
    """The registered name for an external grant, always prefixed."""
    raw = str(spec.get("name") or "").strip()
    if not raw:
        raw = import_path.split(":", 1)[-1].lower()
    raw = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_") or "granted"
    return raw if raw.startswith(GRANT_NAME_PREFIX) else GRANT_NAME_PREFIX + raw


class GrantCapabilityTool:
    """Register an installed callable, or an MCP server, as a tool.

    `irreversible` because it changes what Sim can do -- Guardian gates
    every call, and with `sim.sh`'s auto-approve on, the record in
    `grants.toml` plus the `capabilities` command are what a human
    actually reviews.
    """

    name = "grant_capability"
    description = (
        "Register an installed library callable, or an MCP server, as a tool you can call from "
        "now on. Always granted at the strictest Guardian tier; recorded and revocable."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {
        "type": "object", "required": ["kind"],
        "properties": {
            "kind": {"type": "string"}, "import_path": {"type": "string"},
            "adapter": {"type": "string"}, "name": {"type": "string"},
            "command": {"type": "string"}, "args": {"type": "array"},
            "read_only_tools": {"type": "array"}, "env_keys": {"type": "array"},
            "reason": {"type": "string"},
        },
    }

    def __init__(self, config: Config, *, store: GrantStore | None = None,
                 register=None, start_mcp=None, clock=None, env=None,
                 catalog: list["CatalogEntry"] | None = None) -> None:
        self._config = config
        self._store = store or GrantStore(config.grants_file)
        self._catalog = catalog if catalog is not None else load_catalog(config.mcp_catalog_file)
        # Injected by Execution so this module never imports the Service.
        self._register = register
        self._start_mcp = start_mcp
        self._clock = clock or time.time
        self._env = env

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import os

        env = self._env if self._env is not None else os.environ
        kind = str(args.get("kind") or "").strip().lower()
        if kind not in GRANT_KINDS:
            return ToolResult(ok=False, error=f"refused: kind must be one of {GRANT_KINDS}")
        if self._register is None:
            return ToolResult(ok=False, error="refused: granting is not wired in this process")

        used = sum(1 for g in self._store.load()
                   if g.granted_at[:10] == datetime.fromtimestamp(self._clock(), timezone.utc).date().isoformat())
        if used >= self._config.max_grants_per_day:
            return ToolResult(
                ok=False,
                error=f"refused: {used}/{self._config.max_grants_per_day} capabilities already granted today",
            )

        reason = " ".join(str(args.get("reason") or "").split())[:200]
        now = datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(timespec="seconds")
        base = dict(id=grant_id(self._clock), kind=kind, granted_at=now,
                    granted_by_task=str(getattr(ctx, "task_id", None) or "-"), reason=reason)

        if kind == "external":
            refusal = validate_external(args, self._config)
            if refusal:
                return ToolResult(ok=False, error=refusal)
            import_path = str(args["import_path"]).strip()
            grant = Grant(**base, name=tool_name_for(args, import_path),
                          import_path=import_path, adapter=str(args.get("adapter") or "callable"))
            return await self._grant_external(grant)

        # A catalogued server can be adopted by package name alone: a
        # human already decided it is safe to start and said which of
        # its tools are read-only. Naming a package fills in the rest.
        args, entry = self._apply_catalog(args)
        if entry is None and not self._config.allow_uncatalogued_mcp_grants:
            catalogued = ", ".join(e.package for e in self._catalog) or "(the catalogue is empty)"
            return ToolResult(
                ok=False,
                error=("refused: that server is not in docs/mcp-catalog.toml, which is the list a "
                       "human has approved. Use propose_mcp_server to ask for it, or pick one of: "
                       + catalogued),
            )
        refusal = validate_mcp(args)
        if refusal:
            return ToolResult(ok=False, error=refusal)
        missing = [k for k in (args.get("env_keys") or []) if not env.get(str(k))]
        if missing:
            return ToolResult(
                ok=False,
                error=f"refused: this server needs {', '.join(missing)} in the environment, and it is not set",
            )
        grant = Grant(
            **base, name=str(args["name"]).strip(), command=str(args["command"]).strip(),
            args=tuple(str(a) for a in args.get("args") or ()),
            read_only_tools=tuple(str(a) for a in args.get("read_only_tools") or ()),
            env_keys=tuple(str(a) for a in args.get("env_keys") or ()),
        )
        return await self._grant_mcp(grant, env)

    def _apply_catalog(self, args: dict) -> tuple[dict, "CatalogEntry | None"]:
        """Fill an MCP request in from the catalogue, when it names a
        catalogued package. The catalogue always wins on `command`,
        `args` and `read_only_tools`: those are the human's decision,
        and letting a caller override them would make the catalogue
        decorative."""
        package = str(args.get("package") or "").strip()
        if not package:
            # A caller may also name the package in `args`, which is
            # where it really lives for npx/uvx.
            for candidate in args.get("args") or ():
                if find_in_catalog(str(candidate), self._catalog):
                    package = str(candidate)
                    break
        entry = find_in_catalog(package, self._catalog) if package else None
        if entry is None:
            return args, None
        filled = dict(args)
        filled["command"] = entry.command
        filled["args"] = list(entry.args)
        filled["read_only_tools"] = list(entry.read_only_tools)
        filled["env_keys"] = list(entry.needs_env)
        filled.setdefault("name", _server_name_for(entry.package))
        return filled, entry

    async def _grant_external(self, grant: Grant) -> ToolResult:
        from .external import adapt

        try:
            tools = adapt(grant.as_external_spec())
        except Exception as exc:  # noqa: BLE001 -- a bad import is a refusal, never a crash
            return ToolResult(ok=False, error=f"refused: could not load {grant.import_path}: {exc!r}")
        if not tools:
            return ToolResult(ok=False, error=f"refused: {grant.import_path} produced no callable tool")
        registered = []
        for tool in tools:
            if await self._register(tool, provider="external:granted", marker_arg_key="input"):
                registered.append(tool.name)
        if not registered:
            return ToolResult(ok=False, error=f"refused: {grant.name!r} is already a registered tool name")
        self._store.append(replace(grant, tools=tuple(registered)))
        return ToolResult(
            ok=True,
            output=(f"granted {', '.join(registered)} from {grant.import_path} "
                    f"[{grant.id}]. Call it with a JSON object of its arguments. "
                    "Granted irreversible: every call is gated, and a human can promote or "
                    "revoke it with `capability promote`/`capability revoke`."),
            metadata={"grant_id": grant.id, "tools": registered, "kind": "external"},
        )

    async def _grant_mcp(self, grant: Grant, env) -> ToolResult:
        if self._start_mcp is None:
            return ToolResult(ok=False, error="refused: MCP granting is not wired in this process")
        passthrough = {key: str(env.get(key, "")) for key in grant.env_keys}
        try:
            registered = await self._start_mcp(grant.as_mcp_config(passthrough))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"refused: the server failed to start: {exc!r}")
        if not registered:
            return ToolResult(
                ok=False,
                error=f"refused: {grant.name!r} started no usable tools (it failed to launch, or every name collided)",
            )
        self._store.append(replace(grant, tools=tuple(registered)))
        return ToolResult(
            ok=True,
            output=(f"granted {len(registered)} tool(s) from MCP server {grant.name!r} [{grant.id}]: "
                    + ", ".join(registered)),
            metadata={"grant_id": grant.id, "tools": registered, "kind": "mcp"},
        )


class RevokeCapabilityTool:
    """Take a granted capability away again.

    `reversible`, not `irreversible`: removing a capability can only
    narrow what Sim can do, and a revoke that needed an approval it
    could not get would be the wrong thing to make hard.
    """

    name = "revoke_capability"
    description = "Revoke a capability granted earlier, by grant id or tool name."
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "required": ["target"], "properties": {"target": {"type": "string"}}}

    def __init__(self, config: Config, *, store: GrantStore | None = None, unregister=None) -> None:
        self._config = config
        self._store = store or GrantStore(config.grants_file)
        self._unregister = unregister

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        target = str(args.get("target") or "").strip()
        if not target:
            return ToolResult(ok=False, error="refused: name the grant id or tool to revoke")
        match = next(
            (g for g in self._store.load()
             if g.status == "active" and (g.id == target or g.name == target or target in g.tools)),
            None,
        )
        if match is None:
            return ToolResult(ok=False, error=f"no active grant matches {target!r}")
        self._store.set_status(match.id, "revoked")
        removed = []
        if self._unregister is not None:
            for name in match.tools:
                if await self._unregister(name, reason=f"grant {match.id} revoked"):
                    removed.append(name)
        return ToolResult(
            ok=True,
            output=f"revoked {match.id} ({', '.join(match.tools) or match.name}); "
                   f"{len(removed)} tool(s) unregistered now, and it will not load at the next boot",
            metadata={"grant_id": match.id, "tools": list(match.tools), "unregistered": removed},
        )


# -- the catalogue (D2) -------------------------------------------------


@dataclass(frozen=True)
class CatalogEntry:
    package: str
    command: str
    args: tuple[str, ...]
    read_only_tools: tuple[str, ...] = ()
    needs_env: tuple[str, ...] = ()
    why: str = ""


def load_catalog(path: Path) -> list[CatalogEntry]:
    """The MCP servers a human has said are safe to adopt.

    Human-maintained and Sim-readable only. A malformed file yields
    nothing, which degrades to "nothing may be auto-adopted" -- the
    safe direction.
    """
    if tomllib is None or not Path(path).is_file():
        return []
    try:
        data = tomllib.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    entries = []
    for row in data.get("servers") or []:
        if not isinstance(row, dict) or not row.get("package") or not row.get("command"):
            continue
        entries.append(CatalogEntry(
            package=str(row["package"]), command=str(row["command"]),
            args=tuple(str(a) for a in row.get("args", ())),
            read_only_tools=tuple(str(a) for a in row.get("read_only_tools", ())),
            needs_env=tuple(str(a) for a in row.get("needs_env", ())),
            why=str(row.get("why", "")),
        ))
    return entries


def find_in_catalog(package: str, entries: list[CatalogEntry]) -> CatalogEntry | None:
    wanted = (package or "").strip().lower()
    return next((e for e in entries if e.package.lower() == wanted), None)


def catalog_summary(entries: list[CatalogEntry], env) -> str:
    """What to tell the model about servers it could ask for. Names the
    missing credential rather than hiding a keyed server, so "I could do
    this if you set BRAVE_API_KEY" is sayable."""
    if not entries:
        return ""
    lines = []
    for entry in entries:
        missing = [k for k in entry.needs_env if not (env.get(k) or "").strip()]
        note = f" (needs {', '.join(missing)} -- not set)" if missing else ""
        lines.append(f"- {entry.package}: {entry.why or 'no description'}{note}")
    return (
        "MCP servers you may adopt with grant_capability (kind=mcp), by package name:\n"
        + "\n".join(lines)
    )
