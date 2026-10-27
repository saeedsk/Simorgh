"""The official MCP SDK (modelcontextprotocol/python-sdk, the `mcp`
package) behind the same guarded adapter `mcp.py` feeds -- stage 9 item
12 (`docs/plan/stage-9-consolidation-and-breadth.md`).

`mcp.py` is a hand-rolled stdio JSON-RPC client. It cannot reach a server
that speaks Streamable HTTP or SSE, and every revision of the MCP spec is
this project's to follow. This module runs the SDK's `ClientSession` over
`stdio_client`, the Streamable HTTP client, or `sse_client` for older
servers, and hands the result to the very same `McpToolProxy`. Nothing
about the action path changes: every call to an MCP tool is still
`action.proposed` -> Guardian -> `action.approved` -> verifier ->
dispatch, with no special case for where the tool lives.

The SDK is optional. It is imported inside `try/except ImportError`
(`tests/simorgh/test_module_boundaries.py` allows exactly that), and the
choice of client is `make_client`'s:

- SDK installed: every transport goes through `McpSdkClient`.
- SDK absent: a `stdio` server keeps working through `mcp.McpClient`; an
  `http` or `sse` server is refused by name ("needs `pip install mcp`"),
  which `Service.health()` reports. It is never silently skipped.

Config (`[[execution.mcp_servers]]`): `transport = "stdio" | "http" |
"sse"` (default `stdio`), `url` for the remote two, and `headers`, a map
from HTTP header name to the NAME of a key in `secrets.toml`. The value
is looked up in the subsystem's scoped secrets at start; it is never
written inline in `simorgh.toml`, and a missing key refuses the server.

Not built here (the plan's own out-of-scope list): resources, prompts,
progress and cancellation, OAuth flows. Tool listing reads the first
page only.

Both majors of the SDK are handled where they differ: 1.x names the HTTP
client `streamablehttp_client(url, headers=...)` and takes timeouts as
`timedelta`; 2.x names it `streamable_http_client(url, http_client=...)`
and takes seconds as a float.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable
from urllib.parse import urlsplit

from .mcp import McpClient, McpServerConfig, McpTransportError

TRANSPORTS = ("stdio", "http", "sse")
REMOTE_TRANSPORTS = ("http", "sse")
INSTALL_HINT = "needs `pip install mcp`"


class McpSdkMissing(McpTransportError):
    """An `http`/`sse` server is configured and the SDK is not installed.
    A subclass of `McpTransportError`, so every caller that already turns
    that into a degraded health or a failed `ToolResult` keeps working."""


@dataclass(frozen=True)
class Sdk:
    """The pieces of the installed SDK this module uses, looked up once.
    A dataclass rather than module globals so a test can hand
    `McpSdkClient` a fake without the real package installed."""

    ClientSession: Any
    StdioServerParameters: Any
    stdio_client: Callable
    sse_client: Callable | None = None
    #: 1.x: `streamablehttp_client(url, headers=, timeout=)`.
    streamablehttp_client: Callable | None = None
    #: 2.x: `streamable_http_client(url, http_client=)` plus the SDK's
    #: own factory for that httpx client.
    streamable_http_client: Callable | None = None
    create_http_client: Callable | None = None
    major: int = 1


def load_sdk() -> Sdk | None:
    """The installed SDK, or `None` when the `mcp` package is absent."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return None
    sse = old_http = new_http = http_factory = None
    try:
        from mcp.client.sse import sse_client as sse
    except ImportError:
        pass
    try:
        from mcp.client.streamable_http import streamablehttp_client as old_http
    except ImportError:
        pass
    try:
        from mcp.client.streamable_http import create_mcp_http_client as http_factory
        from mcp.client.streamable_http import streamable_http_client as new_http
    except ImportError:
        pass
    return Sdk(
        ClientSession=ClientSession, StdioServerParameters=StdioServerParameters, stdio_client=stdio_client,
        sse_client=sse, streamablehttp_client=old_http, streamable_http_client=new_http,
        create_http_client=http_factory, major=_sdk_major(),
    )


def _sdk_major() -> int:
    try:
        from importlib.metadata import version

        return int(version("mcp").split(".", 1)[0])
    except Exception:  # noqa: BLE001 -- an unreadable version means "assume 1.x", the older API
        return 1


def sdk_available() -> bool:
    return load_sdk() is not None


def server_host(server: McpServerConfig) -> str:
    """The URL host of a remote server ("" for stdio): what Guardian's
    MCP host allow-list is checked against."""
    if server.transport not in REMOTE_TRANSPORTS:
        return ""
    return (urlsplit(server.url).hostname or "").lower()


def refusal(server: McpServerConfig, *, sdk_present: bool | None = None) -> str | None:
    """Why this server cannot run on this machine, or `None`. Pure apart
    from the SDK check, so the console can ask the same question
    Execution's boot does."""
    if server.transport not in TRANSPORTS:
        return f"mcp server {server.name!r}: unknown transport {server.transport!r} (stdio | http | sse)"
    if server.transport == "stdio":
        if not server.command:
            return f"mcp server {server.name!r}: a stdio server needs a `command`"
        if server.headers:
            return f"mcp server {server.name!r}: `headers` apply to http/sse servers only"
        return None
    parts = urlsplit(server.url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return f"mcp server {server.name!r}: a {server.transport} server needs an http(s) `url`"
    present = sdk_available() if sdk_present is None else sdk_present
    if not present:
        return f"mcp server {server.name!r} ({server.transport}) {INSTALL_HINT}"
    return None


def resolve_headers(server: McpServerConfig, secrets) -> dict[str, str]:
    """`headers` is header name -> secrets key NAME; this looks each value
    up in the subsystem's scoped secrets. A key that is missing or not
    scoped to Execution refuses the server, naming the key."""
    resolved: dict[str, str] = {}
    for header, key in server.headers.items():
        value = None
        if secrets is not None:
            try:
                value = secrets.get(key)
            except Exception:  # noqa: BLE001 -- MissingSecret for an unscoped key: the refusal below says which
                value = None
        if not value:
            raise McpTransportError(
                f"mcp server {server.name!r}: header {header!r} needs secret {key!r} "
                "in secrets.toml, listed in `[execution] secrets`")
        resolved[header] = str(value)
    return resolved


def make_client(server: McpServerConfig, *, secrets=None, fallback: Callable = McpClient,
                sdk: Sdk | None | bool = True):
    """The client for one configured server. Raises `McpSdkMissing` or
    `McpTransportError` for a server that cannot run here; Execution's
    `_start_mcp_server` turns that into a degraded health naming it.

    `fallback` is the no-SDK stdio client; `sdk=True` means "load it",
    `None`/`False` means "act as if it is absent"."""
    loaded = load_sdk() if sdk is True else (sdk or None)
    reason = refusal(server, sdk_present=loaded is not None)
    if reason:
        raise McpSdkMissing(reason) if INSTALL_HINT in reason else McpTransportError(reason)
    if loaded is None:
        return fallback(server)
    return McpSdkClient(server, headers=resolve_headers(server, secrets), sdk=loaded)


def open_transport(sdk: Sdk, server: McpServerConfig, headers: dict[str, str]):
    """An async context manager yielding the SDK's `(read, write, ...)`
    streams for this server. Module-level so a test can swap in the
    SDK's in-memory transport."""
    if server.transport == "stdio":
        params = sdk.StdioServerParameters(
            command=server.command, args=list(server.args), env={**os.environ, **server.env})
        return sdk.stdio_client(params)
    if server.transport == "sse":
        if sdk.sse_client is None:
            raise McpTransportError(f"mcp server {server.name!r}: the installed mcp SDK has no SSE client")
        return sdk.sse_client(server.url, headers=headers or None, timeout=server.timeout_s)
    if sdk.streamablehttp_client is not None:
        return sdk.streamablehttp_client(server.url, headers=headers or None,
                                         timeout=timedelta(seconds=server.timeout_s))
    if sdk.streamable_http_client is not None and sdk.create_http_client is not None:
        return _http_v2(sdk, server, headers)
    raise McpTransportError(f"mcp server {server.name!r}: the installed mcp SDK has no Streamable HTTP client")


@contextlib.asynccontextmanager
async def _http_v2(sdk: Sdk, server: McpServerConfig, headers: dict[str, str]):
    async with sdk.create_http_client(headers=headers or None) as http_client:
        async with sdk.streamable_http_client(server.url, http_client=http_client) as streams:
            yield streams


def _as_dict(obj) -> dict:
    """An SDK result (a pydantic model) as the plain dict shape `mcp.py`'s
    client returns, so `McpToolProxy` reads both the same way."""
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(by_alias=True, exclude_none=True, mode="json")
    return dict(vars(obj))


class McpSdkClient:
    """One MCP server through the SDK, with `mcp.McpClient`'s four
    methods: `start()`, `list_tools()`, `call_tool()`, `close()`.

    The SDK's transports and `ClientSession` are anyio context managers
    that must be entered and exited by the same task. Execution starts a
    server in its boot task and closes it in `stop()`, which may be a
    different one, so a dedicated runner task owns the contexts for the
    session's whole life; calls from any task go through the session's
    own streams."""

    def __init__(self, config: McpServerConfig, *, headers: dict[str, str] | None = None,
                 sdk: Sdk | None = None, transport: Callable | None = None) -> None:
        loaded = sdk or load_sdk()
        if loaded is None:
            raise McpSdkMissing(f"mcp server {config.name!r} ({config.transport}) {INSTALL_HINT}")
        self._config = config
        self._headers = dict(headers or {})
        self._sdk = loaded
        self._transport = transport
        self._session = None
        self._runner: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._ended = ""

    def _read_timeout(self):
        seconds = self._config.timeout_s
        return float(seconds) if self._sdk.major >= 2 else timedelta(seconds=seconds)

    def _open(self):
        if self._transport is not None:
            return self._transport()
        return open_transport(self._sdk, self._config, self._headers)

    async def start(self) -> None:
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._stop = asyncio.Event()
        self._runner = asyncio.create_task(self._run(ready), name=f"mcp-sdk:{self._config.name}")
        try:
            await ready
        except BaseException:
            await self.close()
            raise

    async def _run(self, ready: asyncio.Future) -> None:
        try:
            async with contextlib.AsyncExitStack() as stack:
                streams = await stack.enter_async_context(self._open())
                session = await stack.enter_async_context(
                    self._sdk.ClientSession(streams[0], streams[1], read_timeout_seconds=self._read_timeout()))
                await session.initialize()
                self._session = session
                if not ready.done():
                    ready.set_result(None)
                await self._stop.wait()
        except asyncio.CancelledError:
            if not ready.done():
                ready.set_exception(McpTransportError(f"{self._config.name}: start cancelled"))
            raise
        except Exception as exc:  # noqa: BLE001 -- anyio raises ExceptionGroups; reported, never lost
            self._ended = repr(exc)
            if not ready.done():
                ready.set_exception(McpTransportError(f"{self._config.name}: {exc!r}"))
        finally:
            self._session = None

    def _live_session(self):
        if self._session is None:
            detail = f" ({self._ended})" if self._ended else ""
            raise McpTransportError(f"{self._config.name}: session is not running{detail}")
        return self._session

    async def list_tools(self) -> list[dict]:
        session = self._live_session()
        try:
            result = await session.list_tools()
        except McpTransportError:
            raise
        except Exception as exc:  # noqa: BLE001 -- the SDK's McpError and transport failures alike
            raise McpTransportError(f"{self._config.name}: {exc!r}") from exc
        return [_as_dict(tool) for tool in (getattr(result, "tools", None) or [])]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        session = self._live_session()
        try:
            result = await asyncio.wait_for(session.call_tool(name, arguments), timeout=self._config.timeout_s)
        except (McpTransportError, asyncio.TimeoutError):
            raise
        except Exception as exc:  # noqa: BLE001 -- the SDK's McpError and transport failures alike
            raise McpTransportError(f"{self._config.name}: {exc!r}") from exc
        payload = _as_dict(result)
        if "content" not in payload:
            # 2.x can answer with a result that is not a tool result (an
            # input request). Saying "ok" with no text would be a success
            # that says nothing true, so it is an error, named.
            kind = type(result).__name__
            return {"isError": True, "content": [{"type": "text", "text": f"mcp server returned {kind}, not a tool result"}]}
        return payload

    async def close(self) -> None:
        runner = self._runner
        if runner is None:
            return
        if self._stop is not None:
            self._stop.set()
        if not runner.done():
            try:
                await asyncio.wait_for(asyncio.shield(runner), timeout=5.0)
            except Exception:  # noqa: BLE001 -- a runner that will not exit in time is cancelled
                runner.cancel()
                with contextlib.suppress(BaseException):
                    await runner
        self._runner = None
