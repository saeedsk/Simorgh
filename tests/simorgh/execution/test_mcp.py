"""`execution.mcp` -- the hand-rolled stdio JSON-RPC client for external
MCP tool servers (see `mcp.py`'s own module docstring for why this isn't
the third-party `mcp` SDK). `_FakeMcpProcess` answers `initialize`/
`tools/list`/`tools/call` deterministically from what's written to its
fake stdin, so no test here launches a real subprocess."""

from __future__ import annotations

import json
import unittest

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.mcp import (
    McpClient,
    McpServerConfig,
    McpToolProxy,
    McpTransportError,
    mcp_tool_name,
)


class _FakeMcpProcess:
    """A `asyncio.subprocess.Process`-shaped double: `write()` on the
    "stdin" side synthesizes the matching JSON-RPC response, queued for
    the "stdout" side's `readline()` to hand back."""

    def __init__(self, *, tools: list[dict] | None = None, call_result: dict | None = None,
                 error_on: str | None = None, silent_after: int | None = None) -> None:
        self._tools = tools or []
        self._call_result = call_result if call_result is not None else {
            "content": [{"type": "text", "text": "ok"}], "isError": False,
        }
        self._error_on = error_on
        self._silent_after = silent_after
        self._pending: list[bytes] = []
        self._calls = 0
        self.stdin = self
        self.stdout = self
        self.terminated = False
        self.waited = False
        self.stdin_closed = False

    # -- stdin side -----------------------------------------------------
    def write(self, data: bytes) -> None:
        self._calls += 1
        if self._silent_after is not None and self._calls > self._silent_after:
            return  # simulate a crashed/hung process: never answers again
        request = json.loads(data)
        method, req_id = request.get("method"), request.get("id")
        if req_id is None:
            return  # a notification -- no response expected
        if self._error_on == method:
            message = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": "boom"}}
        elif method == "initialize":
            message = {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {}}}
        elif method == "tools/list":
            message = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self._tools}}
        elif method == "tools/call":
            message = {"jsonrpc": "2.0", "id": req_id, "result": self._call_result}
        else:
            message = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        self._pending.append((json.dumps(message) + "\n").encode("utf-8"))

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.stdin_closed = True

    # -- stdout side ------------------------------------------------------
    async def readline(self) -> bytes:
        return self._pending.pop(0) if self._pending else b""

    def terminate(self) -> None:
        self.terminated = True

    async def wait(self) -> None:
        self.waited = True


def _spawn(process: _FakeMcpProcess):
    async def _do(command, args, env):
        return process
    return _do


def _config(**overrides) -> McpServerConfig:
    return McpServerConfig(name="search", command="fake-server", **overrides)


class TestMcpClientHandshake(unittest.IsolatedAsyncioTestCase):
    async def test_start_sends_initialize_then_the_initialized_notification(self):
        process = _FakeMcpProcess()
        client = McpClient(_config(), spawn=_spawn(process))
        await client.start()
        # Two writes: the initialize request (id=1, consumed as its own
        # response) and the notifications/initialized notification (no
        # id, no response) -- _FakeMcpProcess.write() counts every call.
        self.assertEqual(process._calls, 2)

    async def test_list_tools_returns_the_servers_own_catalog(self):
        spec = {"name": "web_search", "description": "search the web", "inputSchema": {"type": "object"}}
        process = _FakeMcpProcess(tools=[spec])
        client = McpClient(_config(), spawn=_spawn(process))
        await client.start()
        tools = await client.list_tools()
        self.assertEqual(tools, [spec])

    async def test_call_tool_returns_the_result(self):
        process = _FakeMcpProcess(call_result={"content": [{"type": "text", "text": "42"}], "isError": False})
        client = McpClient(_config(), spawn=_spawn(process))
        await client.start()
        result = await client.call_tool("web_search", {"query": "life the universe and everything"})
        self.assertEqual(result["content"][0]["text"], "42")
        self.assertFalse(result["isError"])

    async def test_a_jsonrpc_error_response_raises_transport_error(self):
        process = _FakeMcpProcess(error_on="tools/call")
        client = McpClient(_config(), spawn=_spawn(process))
        await client.start()
        with self.assertRaises(McpTransportError):
            await client.call_tool("web_search", {"query": "x"})

    async def test_a_closed_stream_returns_none_not_a_hang(self):
        process = _FakeMcpProcess(silent_after=0)
        client = McpClient(_config(), spawn=_spawn(process))
        # `start()` itself needs the initialize response -- silent_after=0
        # means even that never arrives, so start() should surface None
        # cleanly via list_tools() reporting an empty catalog rather than
        # hanging (the request/response pair both return None honestly).
        await client.start()
        tools = await client.list_tools()
        self.assertEqual(tools, [])

    async def test_close_terminates_and_waits_on_the_process(self):
        process = _FakeMcpProcess()
        client = McpClient(_config(), spawn=_spawn(process))
        await client.start()
        await client.close()
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)
        self.assertTrue(process.stdin_closed)

    async def test_close_before_start_is_a_no_op(self):
        client = McpClient(_config())
        await client.close()  # must not raise


class TestMcpToolProxy(unittest.IsolatedAsyncioTestCase):
    def _ctx(self) -> ToolContext:
        return ToolContext(action_id="a1", task_id=None, scope={}, constraints={}, data_dir=None, clock=None, logger=None, ledger=None)

    async def test_name_is_namespaced_by_server_and_tool(self):
        process = _FakeMcpProcess()
        client = McpClient(_config(), spawn=_spawn(process))
        proxy = McpToolProxy(client, _config(), {"name": "web_search", "description": "d"})
        self.assertEqual(proxy.name, mcp_tool_name("search", "web_search"))
        self.assertEqual(proxy.name, "mcp_search_web_search")

    async def test_defaults_to_irreversible_unless_named_read_only(self):
        server = _config(read_only_tools=frozenset({"web_search"}))
        client = McpClient(server)
        writer = McpToolProxy(client, server, {"name": "delete_index", "description": "d"})
        reader = McpToolProxy(client, server, {"name": "web_search", "description": "d"})
        self.assertEqual(writer.reversibility, "irreversible")
        self.assertFalse(writer.read_only)
        self.assertEqual(reader.reversibility, "read_only")
        self.assertTrue(reader.read_only)

    async def test_args_schema_comes_from_the_tools_input_schema(self):
        schema = {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}
        proxy = McpToolProxy(McpClient(_config()), _config(), {"name": "web_search", "inputSchema": schema})
        self.assertEqual(proxy.args_schema, schema)

    async def test_run_joins_text_content_blocks_on_success(self):
        process = _FakeMcpProcess(call_result={
            "content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}], "isError": False,
        })
        client = McpClient(_config(), spawn=_spawn(process))
        await client.start()
        proxy = McpToolProxy(client, _config(), {"name": "web_search"})
        result = await proxy.run({"query": "x"}, ctx=self._ctx())
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "first\nsecond")

    async def test_run_reports_iserror_as_a_failed_result_not_a_crash(self):
        process = _FakeMcpProcess(call_result={"content": [{"type": "text", "text": "rate limited"}], "isError": True})
        client = McpClient(_config(), spawn=_spawn(process))
        await client.start()
        proxy = McpToolProxy(client, _config(), {"name": "web_search"})
        result = await proxy.run({"query": "x"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "rate limited")

    async def test_a_transport_error_becomes_a_failed_result_not_a_crash(self):
        process = _FakeMcpProcess(error_on="tools/call")
        client = McpClient(_config(), spawn=_spawn(process))
        await client.start()
        proxy = McpToolProxy(client, _config(), {"name": "web_search"})
        result = await proxy.run({"query": "x"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("mcp call failed", result.error)


if __name__ == "__main__":
    unittest.main()
