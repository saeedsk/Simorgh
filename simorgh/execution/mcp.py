"""MCP (Model Context Protocol) client -- a human-configured, static list
of external tool servers Execution can dispatch to, alongside its own
builtin tools (08-execution.md section 12 Q4: "the `provider: mcp` slot
exists so tool discovery can be deferred" -- this is that deferral,
resolved).

Deliberately NOT built: autonomous server discovery (querying a public
MCP registry and installing whatever it finds at runtime) or a
third-party agent-framework dependency (`langchain-community`,
`composio-core`) to reach it. Both were suggested (the creator relayed a
second model's advice) and both are rejected on this codebase's own
terms: `tests/simorgh/test_module_boundaries.py` enforces "no third-party
import anywhere under `simorgh/`, except one guarded adapter," and
Guardian's whole design is "a reviewed capability, not a self-expanding
attack surface" (`guardian/config.py`'s denylist exists specifically to
funnel real network/subprocess access through a small number of
hand-built, reviewed tools). A human adds a server to `execution.Config.
mcp_servers`; Sim cannot add one to itself. Each discovered tool still
flows through the exact same `action.proposed` -> Guardian ->
`action.approved` pipeline as every builtin tool -- no special-casing.

Transport: MCP's stdio transport is newline-delimited JSON-RPC 2.0 (one
JSON object per line, no embedded newlines -- simpler than LSP's
Content-Length framing). Hand-rolled against `asyncio.subprocess` +
`json` rather than the third-party `mcp` SDK, which isn't installed and
whose only value here would be this same ~150 lines. `spawn` is
injectable (this project's established testing seam -- see
`WebFetchTool`'s own `opener`/`resolver` in `tools.py`) so no test here
launches a real subprocess.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from dataclasses import dataclass, field

from simorgh.contracts.protocols import ToolContext, ToolResult


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    # Tool names (the MCP server's own names, not the `mcp_<server>_<tool>`
    # registered name) this server itself declares side-effect-free.
    # Nothing else about an MCP tool tells Guardian its real
    # reversibility -- the protocol has no such field -- so anything not
    # named here defaults to `irreversible`, the same conservative
    # default `orchestration/tools.py::_TOOL_POLICY` uses for any
    # unrecognized tool.
    read_only_tools: frozenset[str] = frozenset()
    timeout_s: float = 15.0


class McpTransportError(Exception):
    """The server's process failed to start, crashed, sent malformed
    data, or returned a JSON-RPC error. Never raised past a tool's own
    `run()` -- callers convert it into `ToolResult(ok=False, ...)`."""


def mcp_tool_name(server: str, tool: str) -> str:
    return f"mcp_{server}_{tool}"


class McpClient:
    """One MCP server subprocess. `start()` spawns it and performs the
    `initialize`/`notifications/initialized` handshake; `list_tools()`
    and `call_tool()` are the two real RPCs Execution needs."""

    _PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, config: McpServerConfig, *, spawn=None) -> None:
        self._config = config
        self._spawn = spawn or self._default_spawn
        self._process = None
        self._next_id = 0

    @staticmethod
    async def _default_spawn(command: str, args: tuple[str, ...], env: dict[str, str]):
        full_env = {**os.environ, **env}
        return await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=full_env,
        )

    async def start(self) -> None:
        self._process = await self._spawn(self._config.command, self._config.args, self._config.env)
        await self._request("initialize", {
            "protocolVersion": self._PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "simorgh", "version": "2.0"},
        })
        await self._notify("notifications/initialized", {})

    async def list_tools(self) -> list[dict]:
        result = await self._request("tools/list", {})
        return list((result or {}).get("tools", []))

    async def call_tool(self, name: str, arguments: dict) -> dict:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        return result if result is not None else {"isError": True, "content": [{"type": "text", "text": "no response"}]}

    async def close(self) -> None:
        if self._process is None:
            return
        with contextlib.suppress(Exception):
            self._process.stdin.close()
        with contextlib.suppress(ProcessLookupError):
            self._process.terminate()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._process.wait(), timeout=5.0)

    async def _notify(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(self, method: str, params: dict) -> dict | None:
        self._next_id += 1
        req_id = self._next_id
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return await self._recv_response(req_id)

    async def _send(self, obj: dict) -> None:
        line = (json.dumps(obj) + "\n").encode("utf-8")
        self._process.stdin.write(line)
        await self._process.stdin.drain()

    async def _recv_response(self, req_id: int) -> dict | None:
        # The server may interleave notifications (no "id") before the
        # matching response; skip those rather than misreading one as
        # the answer.
        while True:
            raw = await asyncio.wait_for(self._process.stdout.readline(), timeout=self._config.timeout_s)
            if not raw:
                return None  # stream closed -- the process exited or crashed
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("id") != req_id:
                continue
            if "error" in message:
                raise McpTransportError(f"{self._config.name}: {message['error']}")
            return message.get("result")


class McpToolProxy:
    """Adapts one MCP server tool to `contracts.protocols.Tool`. Registered
    dynamically at Execution `start()` -- see `service.py` -- exactly like
    a skill tool, through the same `tool.registered` event World Model's
    `ToolsFacet` already consumes."""

    def __init__(self, client: McpClient, server: McpServerConfig, spec: dict) -> None:
        self._client = client
        self._remote_name = spec.get("name", "")
        self.name = mcp_tool_name(server.name, self._remote_name)
        self.description = spec.get("description") or f"MCP tool {self._remote_name!r} from server {server.name!r}"
        self.read_only = self._remote_name in server.read_only_tools
        self.reversibility = "read_only" if self.read_only else "irreversible"
        self.args_schema = spec.get("inputSchema") or {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        try:
            result = await self._client.call_tool(self._remote_name, args)
        except (McpTransportError, asyncio.TimeoutError, OSError) as exc:
            return ToolResult(ok=False, error=f"mcp call failed: {exc!r}")
        is_error = bool(result.get("isError"))
        text = "\n".join(
            block.get("text", "") for block in result.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return ToolResult(ok=not is_error, output=text, error=(text or "mcp tool error") if is_error else None)
