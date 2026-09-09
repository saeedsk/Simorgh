"""Open-source toolset adapters -- the creator, 2026-09-07: "sim should
be able to seamlessly integrate and use tools from ... Pydantic AI
Toolsets, Composio, LangChain Tools & Toolkit ... it is not good that our
architecture doesn't allow us to re-use external work."

The one architectural property this must not give up: Guardian sees every
call. So an external tool is never handed an agent loop of its own -- it
is wrapped as an ordinary `contracts.protocols.Tool` (`ExternalTool`
below), registered in Execution's registry like `read_file`, proposed
through `action.proposed`, gated by the same pipeline, executed under the
same approval token. The frameworks' own runners/executors are
deliberately not used; only their *tool implementations* are.

Nothing here imports a third-party package statically: every framework
is reached through `importlib` at load time, and any failure -- package
not installed, bad import path, constructor error, no API key -- skips
that one tool with a logged warning. `requirements.txt`'s "everything
else is stdlib-only" floor still holds: a fresh install with no extras
boots exactly as before, it just has no external tools.

Configure in `simorgh.toml`:

    [[execution.external_tools]]
    import_path = "langchain_community.tools:DuckDuckGoSearchRun"
    kind = "langchain"

    [[execution.external_tools]]
    import_path = "my_pkg.tools:my_toolset"     # a pydantic_ai FunctionToolset
    kind = "pydantic_ai"

    [[execution.external_tools]]
    import_path = "composio_langchain:ComposioToolSet"
    kind = "composio"
    kwargs = { actions = ["GITHUB_STAR_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER"] }

    [[execution.external_tools]]
    import_path = "my_pkg.helpers:word_count"    # any plain Python callable
    kind = "callable"

Every adapter presents one string argument, `input`, to the marker layer
(the shape LangChain's own `run(tool_input)` uses); a callable that wants
several keyword arguments receives them when `input` parses as a JSON
object. `orchestration/tools.py::register_tool_policy` learns each tool
from Execution's `tool.registered` announcement (`provider="external"`),
so nothing in orchestration needs editing per tool.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from simorgh.contracts.protocols import ToolContext, ToolResult

KINDS = ("auto", "callable", "langchain", "pydantic_ai", "composio")
_NAME_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True)
class ExternalToolSpec:
    import_path: str
    kind: str = "auto"
    name: str = ""
    # Fail-safe default, matching `mcp.py`'s own pattern (`reversibility
    # = "read_only" if self.read_only else "irreversible"`, i.e. nothing
    # gets Guardian's lighter scrutiny unless a human explicitly grants
    # it): an operator adding `[[execution.external_tools]]` names a
    # third-party callable Sim has never audited -- a LangChain/
    # pydantic_ai/Composio tool can delete files, send messages, spend
    # money, or run arbitrary code. Defaulting to "reversible" here used
    # to mean Guardian's `ReversibilityRule` auto-allowed every such call
    # with no human in the loop unless the operator remembered to set
    # `reversibility = "irreversible"` themselves -- the same shape as
    # the MCP `marker_arg_key` gap: a wrong default classification an
    # operator could ship without noticing (live-caught, 2026-09-08: a
    # `kind="callable"` wrapper around `os.remove` with no explicit
    # `reversibility` was approved and executed with no escalation,
    # permanently deleting a real file). Now unconfigured means the
    # safest tier; `reversibility = "read_only"` or `"reversible"` is an
    # explicit, deliberate loosening the operator has to write down.
    reversibility: str = "irreversible"
    read_only: bool = False
    timeout_s: float = 30.0
    kwargs: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ExternalToolSpec":
        kind = str(data.get("kind", "auto"))
        if kind not in KINDS:
            raise ValueError(f"external tool kind must be one of {KINDS}, not {kind!r}")
        return cls(
            import_path=str(data["import_path"]), kind=kind, name=str(data.get("name", "")),
            reversibility=str(data.get("reversibility", "irreversible")),
            read_only=bool(data.get("read_only", False)),
            timeout_s=float(data.get("timeout_s", 30.0)), kwargs=dict(data.get("kwargs", {}) or {}),
        )


def _safe_name(raw: str) -> str:
    name = _NAME_RE.sub("_", raw.strip().lower()).strip("_")
    return name or "external_tool"


def _resolve(import_path: str) -> Any:
    module_name, sep, attr = import_path.partition(":")
    if not sep:
        module_name, _, attr = import_path.rpartition(".")
    module = importlib.import_module(module_name)
    return getattr(module, attr) if attr else module


class ExternalTool:
    """One wrapped external callable behind Sim's `Tool` protocol."""

    provider = "external"
    args_schema = {"type": "object", "required": ["input"], "properties": {"input": {"type": "string"}}}

    def __init__(self, *, name: str, description: str, fn: Callable[..., Any], spec: ExternalToolSpec,
                 accepts_kwargs: bool = False) -> None:
        self.name = name
        self.description = description
        self.reversibility = spec.reversibility
        self.read_only = spec.read_only
        self._fn = fn
        self._timeout_s = spec.timeout_s
        self._accepts_kwargs = accepts_kwargs

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        raw = args.get("input", "")
        call_kwargs: dict[str, Any] = {}
        positional: tuple = (raw,)
        if self._accepts_kwargs and isinstance(raw, str) and raw.lstrip().startswith("{"):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                call_kwargs, positional = parsed, ()
        timeout = min(ctx.constraints.get("timeout_s", self._timeout_s), self._timeout_s)
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(self._invoke(positional, call_kwargs), timeout=timeout)
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error="timeout", metadata={"duration_s": time.monotonic() - start})
        except Exception as exc:  # noqa: BLE001 -- a third-party failure is a result, never a crash
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}", metadata={"duration_s": time.monotonic() - start})
        return ToolResult(ok=True, output=_render(result), metadata={"duration_s": time.monotonic() - start})

    async def _invoke(self, positional: tuple, kwargs: dict) -> Any:
        if inspect.iscoroutinefunction(self._fn):
            return await self._fn(*positional, **kwargs)
        return await asyncio.to_thread(self._fn, *positional, **kwargs)


def _render(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


# -- per-framework adapters -------------------------------------------------------

def _from_callable(obj: Any, spec: ExternalToolSpec) -> list[ExternalTool]:
    if not callable(obj):
        raise TypeError(f"{spec.import_path} is not callable")
    try:
        params = [p for p in inspect.signature(obj).parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    except (TypeError, ValueError):
        params = []
    name = spec.name or _safe_name(getattr(obj, "__name__", "external_tool"))
    description = inspect.getdoc(obj) or f"External callable {spec.import_path}"
    return [ExternalTool(name=name, description=description, fn=obj, spec=spec, accepts_kwargs=len(params) != 1)]


def _from_langchain(obj: Any, spec: ExternalToolSpec) -> list[ExternalTool]:
    """A LangChain `BaseTool` (instance or class), or a list of them --
    `run(tool_input)` if it has one, else `invoke(input)`. Only the tool's
    own implementation is used; LangChain's agent executors are not."""
    instance = obj(**spec.kwargs) if inspect.isclass(obj) else obj
    items = list(instance) if isinstance(instance, (list, tuple)) else [instance]
    tools: list[ExternalTool] = []
    for item in items:
        fn = getattr(item, "run", None) or getattr(item, "invoke", None)
        if fn is None:
            raise TypeError(f"{spec.import_path}: {item!r} has neither run() nor invoke()")
        name = spec.name if (spec.name and len(items) == 1) else _safe_name(getattr(item, "name", "") or type(item).__name__)
        description = str(getattr(item, "description", "") or f"LangChain tool {name}")
        tools.append(ExternalTool(name=name, description=description, fn=fn, spec=spec))
    return tools


def _from_pydantic_ai(obj: Any, spec: ExternalToolSpec) -> list[ExternalTool]:
    """A pydantic_ai `FunctionToolset` (its `.tools` mapping of name ->
    tool objects carrying `.function`/`.description`), or any plain
    mapping/sequence of callables. Each becomes one tool."""
    instance = obj(**spec.kwargs) if inspect.isclass(obj) else obj
    registry = getattr(instance, "tools", instance)
    if isinstance(registry, Mapping):
        entries = list(registry.items())
    elif isinstance(registry, (list, tuple)):
        entries = [(getattr(t, "name", None) or getattr(t, "__name__", "tool"), t) for t in registry]
    else:
        raise TypeError(f"{spec.import_path}: expected a FunctionToolset, mapping, or sequence of tools")
    tools: list[ExternalTool] = []
    for raw_name, tool in entries:
        fn = getattr(tool, "function", None) or tool
        if not callable(fn):
            raise TypeError(f"{spec.import_path}: tool {raw_name!r} is not callable")
        description = str(getattr(tool, "description", "") or inspect.getdoc(fn) or f"pydantic_ai tool {raw_name}")
        try:
            params = [p for p in inspect.signature(fn).parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
        except (TypeError, ValueError):
            params = []
        tools.append(ExternalTool(name=_safe_name(str(raw_name)), description=description, fn=fn, spec=spec,
                                  accepts_kwargs=len(params) != 1))
    return tools


def _from_composio(obj: Any, spec: ExternalToolSpec) -> list[ExternalTool]:
    """A Composio toolset (`ComposioToolSet`, hosted -- needs
    COMPOSIO_API_KEY in the environment): `get_tools(**kwargs)` returns
    LangChain-shaped tools, wrapped one by one."""
    instance = obj() if inspect.isclass(obj) else obj
    get_tools = getattr(instance, "get_tools", None)
    if get_tools is None:
        raise TypeError(f"{spec.import_path}: expected a Composio toolset with get_tools()")
    return _from_langchain(list(get_tools(**spec.kwargs)), ExternalToolSpec(
        import_path=spec.import_path, kind="langchain", reversibility=spec.reversibility,
        read_only=spec.read_only, timeout_s=spec.timeout_s,
    ))


def _detect_kind(obj: Any) -> str:
    if hasattr(obj, "get_tools"):
        return "composio"
    if hasattr(obj, "tools") and not callable(getattr(obj, "tools", None)):
        return "pydantic_ai"
    if hasattr(obj, "run") or hasattr(obj, "invoke") or isinstance(obj, (list, tuple)):
        return "langchain"
    return "callable"


_ADAPTERS = {
    "callable": _from_callable, "langchain": _from_langchain,
    "pydantic_ai": _from_pydantic_ai, "composio": _from_composio,
}


def adapt(spec: ExternalToolSpec) -> list[ExternalTool]:
    obj = _resolve(spec.import_path)
    kind = spec.kind if spec.kind != "auto" else _detect_kind(obj)
    return _ADAPTERS[kind](obj, spec)


def load_external_tools(specs: tuple[ExternalToolSpec, ...], *, logger=None) -> list[ExternalTool]:
    """Never raises: each spec that can't be loaded is logged and skipped,
    so one missing optional package can't stop Execution from booting."""
    tools: list[ExternalTool] = []
    for spec in specs:
        try:
            tools.extend(adapt(spec))
        except Exception as exc:  # noqa: BLE001 -- optional extras degrade, never crash boot
            if logger is not None:
                logger.warning("external_tool_load_failed", import_path=spec.import_path, detail=repr(exc))
    return tools


__all__ = ["ExternalTool", "ExternalToolSpec", "KINDS", "adapt", "load_external_tools"]
