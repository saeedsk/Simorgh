"""`execution.Service`'s skill-acquisition-as-procedural-memory wiring
(Phase 4 roadmap item 4.7): loading a `skill:<name>` tool on demand in
reaction to `learn.skill.acquired`, and its failure modes. Over a real
(memory-backend) Bus/Ledger and a real Context -- the same shape
`tests/simorgh/memory/test_service.py` uses -- so this package's tests
don't depend on `simorgh.kernel`. The invocation-approval path
(`_on_approved`'s lazy `skill:<name>` fallback) is proven against a REAL
Guardian in `tests/simorgh/integration/test_skill_acquisition_procedural_
memory.py` instead of hand-rolled here, since a genuine `action.approved`
needs Guardian's own HMAC signing machinery to be valid.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.mcp import McpServerConfig
from simorgh.execution.service import Service
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock

_SKILL_SOURCE = 'def run(name="world"):\n    return f"hello {name}"\n'


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class _ExecutionServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "simorgh_skills").mkdir()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="execution", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        self.ctx = Context(
            name="execution", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={"__hmac__": "00" * 32}, clock=self.clock,
            logger=_Logger(), data_dir=self.root / "data",
        )

    async def asyncTearDown(self):
        await self.service.stop()
        await self.bus.stop()
        self._tmp.cleanup()

    async def _start(self, *, config: ExecutionConfig | None = None) -> None:
        self.service = Service(config=config or ExecutionConfig(repo_root=self.root))
        await self.service.start(self.ctx)

    async def _wait_for(self, type_: str, *, predicate=None, timeout: float = 2.0) -> Message | None:
        fut: asyncio.Future = asyncio.get_event_loop().create_future()

        async def _capture(message: Message) -> None:
            if not fut.done() and (predicate is None or predicate(message.payload)):
                fut.set_result(message)

        sub = await self.bus.subscribe(type_, _capture)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            await sub.unsubscribe()

    async def _answer_memory_retrieve_once(self, content: str) -> None:
        async def _on_retrieve(message: Message) -> None:
            await self.bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
                "items": [{"ref": "memory:procedural:1", "kind": "procedural", "content": content,
                           "score": 1.0, "confidence": 1.0, "ts": self.clock.now()}],
                "truncated": False,
            })

        sub = await self.bus.subscribe(topics.MEMORY_RETRIEVE, _on_retrieve)
        self.addAsyncCleanup(sub.unsubscribe)


class TestSkillAcquiredRegistersOnDemand(_ExecutionServiceTestCase):
    async def test_registers_a_skill_tool_and_publishes_tool_registered(self):
        (self.root / "simorgh_skills" / "greet.py").write_text(_SKILL_SOURCE)
        await self._answer_memory_retrieve_once("Greets someone by name.")
        await self._start()

        registered_fut = asyncio.ensure_future(self._wait_for(
            topics.TOOL_REGISTERED, predicate=lambda p: p.get("name") == "skill:greet",
        ))
        await self.bus.publish(Message.new(
            topics.LEARN_SKILL_ACQUIRED, source="learning",
            payload={"name": "greet", "path": "simorgh_skills/greet.py", "tests": 1},
        ))
        registered = await asyncio.wait_for(registered_fut, timeout=5)

        self.assertIsNotNone(registered, "no tool.registered for the acquired skill")
        self.assertEqual(registered.payload["provider"], "skill")
        self.assertEqual(registered.payload["description"], "Greets someone by name.")
        self.assertIn("skill:greet", self.service._registry)  # noqa: SLF001 -- the only handle a test has on the live registry

    async def test_no_memory_responder_falls_back_to_a_synthesized_description(self):
        (self.root / "simorgh_skills" / "lonely.py").write_text(_SKILL_SOURCE)
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))

        registered_fut = asyncio.ensure_future(self._wait_for(
            topics.TOOL_REGISTERED, predicate=lambda p: p.get("name") == "skill:lonely",
        ))
        await self.bus.publish(Message.new(
            topics.LEARN_SKILL_ACQUIRED, source="learning",
            payload={"name": "lonely", "path": "simorgh_skills/lonely.py", "tests": 1},
        ))
        registered = await asyncio.wait_for(registered_fut, timeout=5)

        self.assertIsNotNone(registered)
        self.assertIn("lonely", registered.payload["description"])

    async def test_a_path_outside_readable_roots_is_refused_without_registering(self):
        await self._start()

        await self.bus.publish(Message.new(
            topics.LEARN_SKILL_ACQUIRED, source="learning",
            payload={"name": "sneaky", "path": "../../etc/passwd", "tests": 0},
        ))
        registered = await self._wait_for(
            topics.TOOL_REGISTERED, predicate=lambda p: p.get("name") == "skill:sneaky", timeout=0.3,
        )

        self.assertIsNone(registered)
        self.assertNotIn("skill:sneaky", self.service._registry)  # noqa: SLF001

    async def test_a_second_acquisition_of_the_same_name_does_not_re_register(self):
        (self.root / "simorgh_skills" / "twice.py").write_text(_SKILL_SOURCE)
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))

        seen: list[Message] = []

        async def _on_registered(message: Message) -> None:
            if message.payload.get("name") == "skill:twice":
                seen.append(message)

        sub = await self.bus.subscribe(topics.TOOL_REGISTERED, _on_registered)
        for _ in range(2):
            await self.bus.publish(Message.new(
                topics.LEARN_SKILL_ACQUIRED, source="learning",
                payload={"name": "twice", "path": "simorgh_skills/twice.py", "tests": 1},
            ))
            # Each `_load_skill` awaits a real (timeout-bounded) `memory.
            # retrieve` request with no responder here -- a zero-length
            # `asyncio.sleep(0)` never lets that real-time timeout elapse,
            # so give it actual wall-clock room instead.
            await asyncio.sleep(0.1)
        await sub.unsubscribe()

        self.assertEqual(len(seen), 1)


class _FakeMcpClient:
    """Stands in for `mcp.McpClient` at the `Service._start_mcp_server`
    boundary -- `execution/test_mcp.py` already covers the real client's
    wire protocol against a fake process; this only has to prove
    `Service` wires registration/error-handling correctly."""

    def __init__(self, server: McpServerConfig, *, tools=None, start_exc: Exception | None = None) -> None:
        self.server = server
        self._tools = tools if tools is not None else []
        self._start_exc = start_exc
        self.started = False
        self.closed = False

    async def start(self) -> None:
        if self._start_exc is not None:
            raise self._start_exc
        self.started = True

    async def list_tools(self) -> list[dict]:
        return self._tools

    async def close(self) -> None:
        self.closed = True


class TestMcpServerWiring(_ExecutionServiceTestCase):
    """`Service._start_mcp_server` (`execution/mcp.py`'s own module
    docstring: a human-configured, static server list, registered
    through the same `tool.registered` path a skill uses). Asserts
    against `self.service._registry` directly, matching this file's
    existing skill-registration tests -- a `tool.registered` subscription
    set up before `start()` doesn't reliably observe a publish that
    happens synchronously *during* `start()` itself over this bus's
    memory backend (unlike the skill tests above, whose publish is a
    later, test-triggered `learn.skill.acquired`)."""

    async def _boot(self, *, config: ExecutionConfig) -> None:
        self.service = Service(config=config)
        await self.service.start(self.ctx)

    async def test_registers_every_tool_a_configured_server_declares(self):
        server = McpServerConfig(name="search", command="fake-search")
        tools = [
            {"name": "web_search", "description": "search the web", "inputSchema": {"type": "object"}},
            {"name": "web_search_news", "description": "search news", "inputSchema": {"type": "object"}},
        ]
        with unittest.mock.patch("simorgh.execution.service.McpClient", lambda s: _FakeMcpClient(s, tools=tools)):
            await self._boot(config=ExecutionConfig(repo_root=self.root, mcp_servers=(server,)))

        self.assertIn("mcp_search_web_search", self.service._registry)  # noqa: SLF001
        self.assertIn("mcp_search_web_search_news", self.service._registry)  # noqa: SLF001
        self.assertEqual(self.service._registry["mcp_search_web_search"].description, "search the web")  # noqa: SLF001

    async def test_a_server_named_read_only_tool_registers_as_read_only(self):
        server = McpServerConfig(name="search", command="fake-search", read_only_tools=frozenset({"web_search"}))
        tools = [{"name": "web_search", "description": "d", "inputSchema": {}}]
        with unittest.mock.patch("simorgh.execution.service.McpClient", lambda s: _FakeMcpClient(s, tools=tools)):
            await self._boot(config=ExecutionConfig(repo_root=self.root, mcp_servers=(server,)))
        tool = self.service._registry["mcp_search_web_search"]  # noqa: SLF001
        self.assertEqual(tool.reversibility, "read_only")
        self.assertTrue(tool.read_only)

    async def test_a_server_that_fails_to_start_degrades_instead_of_crashing_boot(self):
        server = McpServerConfig(name="broken", command="does-not-exist")
        with unittest.mock.patch(
            "simorgh.execution.service.McpClient",
            lambda s: _FakeMcpClient(s, start_exc=OSError("no such file")),
        ):
            await self._boot(config=ExecutionConfig(repo_root=self.root, mcp_servers=(server,)))

        self.assertEqual([n for n in self.service._registry if n.startswith("mcp_")], [])  # noqa: SLF001
        health = await self.service.health()
        self.assertEqual(health.status, "degraded")
        self.assertIn("broken", health.detail)

    async def test_one_broken_server_does_not_block_a_working_one(self):
        broken = McpServerConfig(name="broken", command="does-not-exist")
        working = McpServerConfig(name="search", command="fake-search")
        tools = [{"name": "web_search", "description": "d", "inputSchema": {}}]

        def _factory(server: McpServerConfig):
            if server.name == "broken":
                return _FakeMcpClient(server, start_exc=OSError("no such file"))
            return _FakeMcpClient(server, tools=tools)

        with unittest.mock.patch("simorgh.execution.service.McpClient", _factory):
            await self._boot(config=ExecutionConfig(repo_root=self.root, mcp_servers=(broken, working)))

        self.assertEqual([n for n in self.service._registry if n.startswith("mcp_")], ["mcp_search_web_search"])  # noqa: SLF001

    async def test_stop_closes_every_started_mcp_client(self):
        server = McpServerConfig(name="search", command="fake-search")
        clients: list[_FakeMcpClient] = []

        def _factory(s: McpServerConfig) -> _FakeMcpClient:
            client = _FakeMcpClient(s, tools=[{"name": "web_search", "description": "d", "inputSchema": {}}])
            clients.append(client)
            return client

        with unittest.mock.patch("simorgh.execution.service.McpClient", _factory):
            self.service = Service(config=ExecutionConfig(repo_root=self.root, mcp_servers=(server,)))
            await self.service.start(self.ctx)

        await self.service.stop()
        self.assertTrue(clients[0].closed)


if __name__ == "__main__":
    unittest.main()
