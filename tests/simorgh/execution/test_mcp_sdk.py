"""`execution.mcp_sdk` -- the official MCP SDK behind the guarded adapter
(stage 9 item 12).

Two halves. The fakes (`_FakeSdk`) stand in for the `mcp` package, so the
transport choice, header lookup, refusals and the runner-task lifecycle
are tested on every machine, SDK or not. The `TestWithTheRealSdk` classes
use the SDK's own in-memory transport and are skipped when the package is
absent. Both drive a stdio and an HTTP server through the real Guardian
and Execution booted by the Kernel, and check that a denied call never
reaches the server.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolContext
from simorgh.execution import mcp_sdk
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.mcp import McpClient, McpServerConfig, McpToolProxy, McpTransportError
from simorgh.execution.mcp_sdk import (
    INSTALL_HINT,
    McpSdkClient,
    McpSdkMissing,
    Sdk,
    make_client,
    open_transport,
    refusal,
    resolve_headers,
    server_host,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HAS_SDK = mcp_sdk.load_sdk() is not None


# -- a fake SDK -----------------------------------------------------------------
class _Model:
    """A pydantic-shaped result: `model_dump(by_alias=, exclude_none=, mode=)`."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def model_dump(self, **_kwargs) -> dict:
        return dict(self._data)


class _FakeServer:
    """What the fake session talks to: a tool catalog and a call log."""

    def __init__(self, tools: list[dict] | None = None, *, fail_initialize: bool = False,
                 call_raises: Exception | None = None, call_result: object = None) -> None:
        self.tools = tools if tools is not None else [
            {"name": "add", "description": "add two numbers",
             "inputSchema": {"type": "object", "required": ["a", "b"],
                             "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}},
        ]
        self.fail_initialize = fail_initialize
        self.call_raises = call_raises
        self.call_result = call_result
        self.calls: list[tuple[str, dict]] = []
        self.entered_by: asyncio.Task | None = None
        self.exited_by: asyncio.Task | None = None
        self.session_kwargs: dict = {}


class _FakeSession:
    def __init__(self, server: _FakeServer, read, write, **kwargs) -> None:
        self._server = server
        server.session_kwargs = {"read": read, "write": write, **kwargs}

    async def __aenter__(self):
        self._server.entered_by = asyncio.current_task()
        return self

    async def __aexit__(self, *exc):
        self._server.exited_by = asyncio.current_task()
        return False

    async def initialize(self):
        if self._server.fail_initialize:
            raise RuntimeError("handshake refused")

    async def list_tools(self):
        return SimpleNamespace(tools=[_Model(t) for t in self._server.tools])

    async def call_tool(self, name, arguments):
        self._server.calls.append((name, dict(arguments or {})))
        if self._server.call_raises is not None:
            raise self._server.call_raises
        if self._server.call_result is not None:
            return self._server.call_result
        if name == "add":
            text = str(int(arguments["a"]) + int(arguments["b"]))
        else:
            text = "ok"
        return _Model({"content": [{"type": "text", "text": text}], "isError": False})


def _fake_sdk(server: _FakeServer, *, major: int = 1, opened: list | None = None) -> Sdk:
    opened = opened if opened is not None else []

    @contextlib.asynccontextmanager
    async def _streams(kind, *args, **kwargs):
        opened.append((kind, args, kwargs))
        yield ("read", "write")

    @contextlib.asynccontextmanager
    async def _http_client(**kwargs):
        opened.append(("httpx", (), kwargs))
        yield "http-client"

    return Sdk(
        ClientSession=lambda read, write, **kw: _FakeSession(server, read, write, **kw),
        StdioServerParameters=lambda **kw: SimpleNamespace(**kw),
        stdio_client=lambda params: _streams("stdio", params),
        sse_client=lambda url, **kw: _streams("sse", url, **kw),
        streamablehttp_client=(lambda url, **kw: _streams("http1", url, **kw)) if major == 1 else None,
        streamable_http_client=(lambda url, **kw: _streams("http2", url, **kw)) if major >= 2 else None,
        create_http_client=_http_client if major >= 2 else None,
        major=major,
    )


def _stdio(**kw) -> McpServerConfig:
    return McpServerConfig(name=kw.pop("name", "local"), command=kw.pop("command", "fake-server"), **kw)


def _http(**kw) -> McpServerConfig:
    return McpServerConfig(name=kw.pop("name", "remote"), transport=kw.pop("transport", "http"),
                           url=kw.pop("url", "https://mcp.example.test/mcp"), **kw)


def _ctx() -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={}, data_dir=None,
                       clock=None, logger=None, ledger=None)


# -- config, refusals, headers ----------------------------------------------------
class TestConfig(unittest.TestCase):
    def test_from_mapping_reads_transport_url_and_header_key_names(self):
        config = ExecutionConfig.from_mapping({"mcp_servers": [
            {"name": "remote", "transport": "http", "url": "https://mcp.example.test/mcp",
             "headers": {"Authorization": "REMOTE_MCP_TOKEN"}},
            {"name": "local", "command": "npx", "args": ["-y", "x"]},
        ]})
        remote, local = config.mcp_servers
        self.assertEqual((remote.transport, remote.url, remote.command), ("http", "https://mcp.example.test/mcp", ""))
        self.assertEqual(remote.headers, {"Authorization": "REMOTE_MCP_TOKEN"})
        self.assertEqual((local.transport, local.url, local.headers), ("stdio", "", {}))


class TestRefusal(unittest.TestCase):
    def test_a_stdio_server_runs_with_or_without_the_sdk(self):
        self.assertIsNone(refusal(_stdio(), sdk_present=False))
        self.assertIsNone(refusal(_stdio(), sdk_present=True))

    def test_http_and_sse_without_the_sdk_are_refused_by_name(self):
        for transport in ("http", "sse"):
            reason = refusal(_http(name="search", transport=transport), sdk_present=False)
            self.assertIn("'search'", reason)
            self.assertIn(transport, reason)
            self.assertIn("pip install mcp", reason)

    def test_http_with_the_sdk_is_not_refused(self):
        self.assertIsNone(refusal(_http(), sdk_present=True))

    def test_an_unknown_transport_or_a_missing_url_or_command_is_refused(self):
        self.assertIn("unknown transport", refusal(_stdio(transport="websocket"), sdk_present=True))
        self.assertIn("http(s) `url`", refusal(_http(url="ftp://x"), sdk_present=True))
        self.assertIn("http(s) `url`", refusal(_http(url=""), sdk_present=True))
        self.assertIn("needs a `command`", refusal(_stdio(command=""), sdk_present=True))
        self.assertIn("http/sse servers only", refusal(_stdio(headers={"X": "K"}), sdk_present=True))

    def test_server_host_is_the_lowercased_url_host_and_empty_for_stdio(self):
        self.assertEqual(server_host(_http(url="https://MCP.Example.test:8443/mcp")), "mcp.example.test")
        self.assertEqual(server_host(_stdio()), "")


class TestHeaders(unittest.TestCase):
    def test_header_values_come_from_secrets_by_key_name(self):
        server = _http(headers={"Authorization": "REMOTE_MCP_TOKEN"})
        self.assertEqual(resolve_headers(server, {"REMOTE_MCP_TOKEN": "Bearer s3cret"}),
                         {"Authorization": "Bearer s3cret"})

    def test_a_missing_or_unscoped_key_refuses_and_names_the_key(self):
        server = _http(headers={"Authorization": "REMOTE_MCP_TOKEN"})

        class _Scoped:
            def get(self, name):
                raise KeyError(f"{name} (not scoped to this subsystem)")

        for secrets in ({}, None, _Scoped()):
            with self.assertRaises(McpTransportError) as caught:
                resolve_headers(server, secrets)
            self.assertIn("REMOTE_MCP_TOKEN", str(caught.exception))
            self.assertNotIn("s3cret", str(caught.exception))


class TestMakeClient(unittest.TestCase):
    def test_without_the_sdk_stdio_falls_back_to_the_hand_rolled_client(self):
        client = make_client(_stdio(), sdk=None)
        self.assertIsInstance(client, McpClient)

    def test_without_the_sdk_http_raises_the_named_refusal(self):
        with self.assertRaises(McpSdkMissing) as caught:
            make_client(_http(name="search"), sdk=None)
        self.assertIn(INSTALL_HINT, str(caught.exception))
        self.assertIsInstance(caught.exception, McpTransportError)

    def test_with_the_sdk_every_transport_gets_the_sdk_client(self):
        sdk = _fake_sdk(_FakeServer())
        for server in (_stdio(), _http(), _http(transport="sse")):
            self.assertIsInstance(make_client(server, sdk=sdk), McpSdkClient)

    def test_with_the_sdk_header_secrets_are_resolved_at_build_time(self):
        sdk = _fake_sdk(_FakeServer())
        server = _http(headers={"Authorization": "REMOTE_MCP_TOKEN"})
        with self.assertRaises(McpTransportError):
            make_client(server, secrets={}, sdk=sdk)
        client = make_client(server, secrets={"REMOTE_MCP_TOKEN": "Bearer t"}, sdk=sdk)
        self.assertEqual(client._headers, {"Authorization": "Bearer t"})  # noqa: SLF001


# -- transports -------------------------------------------------------------------
class TestOpenTransport(unittest.IsolatedAsyncioTestCase):
    async def _open(self, server, *, major=1, headers=None):
        opened: list = []
        sdk = _fake_sdk(_FakeServer(), major=major, opened=opened)
        async with open_transport(sdk, server, headers or {}) as streams:
            self.assertEqual(streams, ("read", "write"))
        return opened

    async def test_stdio_launches_the_command_with_args_and_env(self):
        opened = await self._open(_stdio(command="npx", args=("-y", "pkg"), env={"K": "v"}))
        kind, (params,), _ = opened[0]
        self.assertEqual(kind, "stdio")
        self.assertEqual((params.command, params.args, params.env["K"]), ("npx", ["-y", "pkg"], "v"))

    async def test_sse_passes_url_headers_and_timeout(self):
        opened = await self._open(_http(transport="sse", timeout_s=7.0), headers={"Authorization": "t"})
        self.assertEqual(opened[0], ("sse", ("https://mcp.example.test/mcp",),
                                     {"headers": {"Authorization": "t"}, "timeout": 7.0}))

    async def test_http_on_sdk_1x_uses_streamablehttp_client_with_headers(self):
        opened = await self._open(_http(), headers={"Authorization": "t"})
        kind, args, kwargs = opened[0]
        self.assertEqual((kind, args, kwargs["headers"]), ("http1", ("https://mcp.example.test/mcp",), {"Authorization": "t"}))

    async def test_http_on_sdk_2x_builds_an_http_client_carrying_the_headers(self):
        opened = await self._open(_http(), major=2, headers={"Authorization": "t"})
        self.assertEqual(opened[0], ("httpx", (), {"headers": {"Authorization": "t"}}))
        self.assertEqual(opened[1], ("http2", ("https://mcp.example.test/mcp",), {"http_client": "http-client"}))


# -- the client's lifecycle ---------------------------------------------------------
class TestMcpSdkClient(unittest.IsolatedAsyncioTestCase):
    async def test_lists_and_calls_through_the_session(self):
        server = _FakeServer()
        client = McpSdkClient(_stdio(), sdk=_fake_sdk(server))
        await client.start()
        try:
            tools = await client.list_tools()
            self.assertEqual([t["name"] for t in tools], ["add"])
            result = await client.call_tool("add", {"a": 2, "b": 3})
            self.assertEqual(result["content"][0]["text"], "5")
            self.assertEqual(server.calls, [("add", {"a": 2, "b": 3})])
        finally:
            await client.close()

    async def test_read_timeout_is_a_timedelta_on_1x_and_seconds_on_2x(self):
        for major, expected in ((1, "timedelta"), (2, "float")):
            server = _FakeServer()
            client = McpSdkClient(_stdio(timeout_s=4.0), sdk=_fake_sdk(server, major=major))
            await client.start()
            await client.close()
            self.assertEqual(type(server.session_kwargs["read_timeout_seconds"]).__name__, expected)

    async def test_contexts_are_entered_and_exited_by_one_task_even_when_closed_from_another(self):
        server = _FakeServer()
        client = McpSdkClient(_stdio(), sdk=_fake_sdk(server))
        await client.start()
        await asyncio.create_task(client.close())
        self.assertIsNotNone(server.entered_by)
        self.assertIs(server.entered_by, server.exited_by)
        self.assertIsNot(server.entered_by, asyncio.current_task())

    async def test_a_failed_handshake_raises_a_transport_error_from_start(self):
        client = McpSdkClient(_stdio(), sdk=_fake_sdk(_FakeServer(fail_initialize=True)))
        with self.assertRaises(McpTransportError) as caught:
            await client.start()
        self.assertIn("handshake refused", str(caught.exception))
        await client.close()  # already reaped; must not raise

    async def test_an_sdk_error_on_a_call_becomes_a_transport_error(self):
        client = McpSdkClient(_stdio(), sdk=_fake_sdk(_FakeServer(call_raises=RuntimeError("McpError: boom"))))
        await client.start()
        try:
            with self.assertRaises(McpTransportError):
                await client.call_tool("add", {"a": 1, "b": 1})
        finally:
            await client.close()

    async def test_a_result_that_is_not_a_tool_result_is_an_error_not_an_empty_success(self):
        client = McpSdkClient(_stdio(), sdk=_fake_sdk(_FakeServer(call_result=_Model({"inputRequests": {}}))))
        await client.start()
        try:
            proxy = McpToolProxy(client, _stdio(), {"name": "add"})
            result = await proxy.run({"a": 1, "b": 1}, ctx=_ctx())
        finally:
            await client.close()
        self.assertFalse(result.ok)
        self.assertIn("not a tool result", result.error)

    async def test_a_call_after_close_fails_cleanly_through_the_proxy(self):
        client = McpSdkClient(_stdio(), sdk=_fake_sdk(_FakeServer()))
        await client.start()
        await client.close()
        proxy = McpToolProxy(client, _stdio(), {"name": "add"})
        result = await proxy.run({"a": 1, "b": 1}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("session is not running", result.error)

    async def test_constructing_without_the_sdk_is_the_named_refusal(self):
        with mock.patch.object(mcp_sdk, "load_sdk", lambda: None):
            with self.assertRaises(McpSdkMissing):
                McpSdkClient(_http())


# -- Execution boot: refusals in health(), SDK tools registered ---------------------
from tests.simorgh.execution.test_service import _ExecutionServiceTestCase  # noqa: E402


class TestExecutionBoot(_ExecutionServiceTestCase):
    async def _boot(self, servers, *, sdk) -> None:
        from simorgh.execution.service import Service

        with mock.patch.object(mcp_sdk, "load_sdk", lambda: sdk):
            self.service = Service(config=ExecutionConfig(repo_root=self.root, mcp_servers=tuple(servers)))
            await self.service.start(self.ctx)

    async def test_an_http_server_without_the_sdk_is_named_in_health_and_registers_nothing(self):
        await self._boot([_http(name="search")], sdk=None)
        health = await self.service.health()
        self.assertEqual(health.status, "degraded")
        self.assertIn("'search'", health.detail)
        self.assertIn("pip install mcp", health.detail)
        self.assertEqual([n for n in self.service._registry if n.startswith("mcp_")], [])  # noqa: SLF001

    async def test_with_the_sdk_stdio_and_http_tools_both_register(self):
        await self._boot([_stdio(), _http()], sdk=_fake_sdk(_FakeServer()))
        names = sorted(n for n in self.service._registry if n.startswith("mcp_"))  # noqa: SLF001
        self.assertEqual(names, ["mcp_local_add", "mcp_remote_add"])
        self.assertNotIn("mcp", (await self.service.health()).detail)

    async def test_a_missing_header_secret_degrades_and_names_the_key(self):
        await self._boot([_http(headers={"Authorization": "REMOTE_MCP_TOKEN"})], sdk=_fake_sdk(_FakeServer()))
        health = await self.service.health()
        self.assertEqual(health.status, "degraded")
        self.assertIn("REMOTE_MCP_TOKEN", health.detail)


# -- through the real Guardian and Execution, booted by the Kernel -----------------
def _proposal(action_id: str, *, tool: str, args: dict) -> Message:
    return Message.new(
        topics.ACTION_PROPOSED, source="test",
        payload={"action_id": action_id, "tool": tool, "args": args,
                 "scope": {"network": False}, "reversibility": "read_only",
                 "rationale": "mcp sdk test", "proposed_by": "test"},
    )


class _GuardianPath:
    """Mixin: boot a Kernel whose Execution has a stdio and an HTTP MCP
    server, both declaring `add` read-only, and drive proposals at them."""

    SERVERS = (
        McpServerConfig(name="local", command="unused", read_only_tools=frozenset({"add"})),
        McpServerConfig(name="remote", transport="http", url="https://mcp.example.test/mcp",
                        read_only_tools=frozenset({"add"})),
    )

    async def _boot_kernel(self):
        from simorgh.execution.service import Service as ExecutionService
        from simorgh.guardian.config import Config as GuardianConfig
        from simorgh.guardian.service import Service as GuardianService
        from simorgh.kernel import registry as kernel_registry
        from simorgh.kernel.config import LoadedConfig
        from simorgh.kernel.secrets import EnvSecretStore
        from simorgh.kernel.service import Kernel

        real = kernel_registry.build_factories
        servers = self.SERVERS

        def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
            factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl,
                             guardian_config=guardian_config)
            factories["guardian"] = lambda: GuardianService(config=GuardianConfig(mode="guarded"))
            factories["execution"] = lambda: ExecutionService(
                config=ExecutionConfig(repo_root=_REPO_ROOT, mcp_servers=servers))
            return factories

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp.name}}, None), secrets=EnvSecretStore({}))
        patcher = mock.patch("simorgh.kernel.service.build_factories", new=_build)
        patcher.start()
        self.addCleanup(patcher.stop)
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        self.events: list[Message] = []

        async def _on(message: Message) -> None:
            self.events.append(message)

        await kernel.bus.subscribe(topics.ACTION_DENIED, _on)
        await kernel.bus.subscribe(topics.ACTION_RESULT, _on, group="mcp-sdk-test")
        return kernel

    async def _await_outcome(self, action_id: str) -> Message | None:
        for _ in range(500):
            for message in self.events:
                if message.payload.get("action_id") == action_id:
                    return message
            await asyncio.sleep(0.01)
        return None

    async def _drive(self, kernel, calls: list) -> None:
        for server in ("local", "remote"):
            await kernel.bus.publish(_proposal(f"ok-{server}", tool=f"mcp_{server}_add", args={"a": 2, "b": 3}))
            result = await self._await_outcome(f"ok-{server}")
            self.assertIsNotNone(result, f"no outcome for mcp_{server}_add")
            self.assertEqual(result.type, topics.ACTION_RESULT, result.payload)
            self.assertTrue(result.payload["ok"], result.payload)
            self.assertIn("5", result.payload["stdout_preview"])
        seen = len(calls)
        self.assertEqual(seen, 2)

        # Missing a required argument: Guardian's SchemaRule denies it
        # against the schema the server itself declared, so the server
        # never sees the call.
        await kernel.bus.publish(_proposal("denied-1", tool="mcp_remote_add", args={"a": 2}))
        denied = await self._await_outcome("denied-1")
        self.assertIsNotNone(denied)
        self.assertEqual(denied.type, topics.ACTION_DENIED, denied.payload)
        await asyncio.sleep(0.1)
        self.assertEqual(len(calls), seen, "a denied call reached the server")


class TestGuardianPathWithAFakeSdk(_GuardianPath, unittest.IsolatedAsyncioTestCase):
    async def test_stdio_and_http_tools_are_called_through_guardian_and_a_denial_never_arrives(self):
        server = _FakeServer()
        with mock.patch.object(mcp_sdk, "load_sdk", lambda: _fake_sdk(server)):
            kernel = await self._boot_kernel()
        await self._drive(kernel, server.calls)


def _sdk_memory_server(calls: list):
    """An SDK server with one tool, `add`, for the SDK major installed."""
    try:
        from mcp.server.mcpserver import MCPServer as _Server  # 2.x
    except ImportError:
        from mcp.server.fastmcp import FastMCP as _Server  # 1.x
    server = _Server("sim-test")

    @server.tool()
    def add(a: int, b: int) -> str:
        """Add two numbers."""
        calls.append((a, b))
        return str(a + b)

    return server


def _sdk_memory_transport(server):
    """The SDK's in-memory transport to `server`, as a zero-argument
    factory of async context managers yielding `(read, write)`."""
    try:
        from mcp.client._memory import InMemoryTransport  # 2.x
    except ImportError:
        InMemoryTransport = None
    if InMemoryTransport is not None:
        return lambda: InMemoryTransport(server)

    import anyio
    from mcp.shared.memory import create_client_server_memory_streams

    low = server._mcp_server  # noqa: SLF001 -- 1.x has no public handle on the low-level server

    @contextlib.asynccontextmanager
    async def _open():
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(low.run, server_streams[0], server_streams[1],
                                 low.create_initialization_options())
                yield client_streams
                group.cancel_scope.cancel()

    return _open


@unittest.skipUnless(_HAS_SDK, "the `mcp` SDK is not installed")
class TestWithTheRealSdk(_GuardianPath, unittest.IsolatedAsyncioTestCase):
    async def test_the_sdk_client_lists_and_calls_over_its_in_memory_transport(self):
        calls: list = []
        transport = _sdk_memory_transport(_sdk_memory_server(calls))
        client = McpSdkClient(_stdio(), transport=transport)
        await client.start()
        try:
            tools = await client.list_tools()
            self.assertEqual([t["name"] for t in tools], ["add"])
            self.assertIn("a", tools[0]["inputSchema"]["properties"])
            result = await McpToolProxy(client, _stdio(), tools[0]).run({"a": 2, "b": 40}, ctx=_ctx())
        finally:
            await client.close()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "42")
        self.assertEqual(calls, [(2, 40)])

    async def test_stdio_and_http_tools_are_called_through_guardian_and_a_denial_never_arrives(self):
        calls: list = []
        transports = {name: _sdk_memory_transport(_sdk_memory_server(calls)) for name in ("local", "remote")}
        with mock.patch.object(mcp_sdk, "open_transport", lambda sdk, server, headers: transports[server.name]()):
            kernel = await self._boot_kernel()
        await self._drive(kernel, calls)


if __name__ == "__main__":
    unittest.main()


