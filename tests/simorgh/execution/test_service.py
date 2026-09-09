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


class TestSkillsOnDiskAreAnnouncedAtBoot(_ExecutionServiceTestCase):
    """A skill Sim wrote in an earlier session must be REACHABLE in this
    one. Loading stays on demand by design; the gap was that nothing
    ever told the model such a skill existed, so it could never name
    one, so the lazy load could never fire -- the skill was a committed
    file and nothing else (audit, 2026-09-08)."""

    async def _announced(self) -> set[str]:
        seen: set[str] = set()

        async def _on(message):
            if message.payload.get("provider") == "skill":
                seen.add(message.payload["name"])

        await self.bus.subscribe(topics.TOOL_REGISTERED, _on)
        return seen

    async def test_a_skill_already_on_disk_is_announced_at_boot(self):
        (self.root / "simorgh_skills" / "earlier.py").write_text(_SKILL_SOURCE)
        seen = await self._announced()
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))
        for _ in range(50):
            if seen:
                break
            await asyncio.sleep(0.01)
        self.assertIn("skill:earlier", seen)

    async def test_announcing_does_not_read_or_load_the_source(self):
        """The documented property: no boot-time directory scan that
        loads every skill ever acquired."""
        (self.root / "simorgh_skills" / "earlier.py").write_text(_SKILL_SOURCE)
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))
        self.assertNotIn("skill:earlier", self.service._registry)  # noqa: SLF001

    async def test_several_are_announced_and_dunder_files_are_skipped(self):
        for name in ("alpha", "beta"):
            (self.root / "simorgh_skills" / f"{name}.py").write_text(_SKILL_SOURCE)
        (self.root / "simorgh_skills" / "__init__.py").write_text("")
        seen = await self._announced()
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))
        for _ in range(50):
            if len(seen) >= 2:
                break
            await asyncio.sleep(0.01)
        self.assertIn("skill:alpha", seen)
        self.assertIn("skill:beta", seen)
        self.assertNotIn("skill:__init__", seen)

    async def test_no_skill_directory_is_not_an_error(self):
        import shutil

        shutil.rmtree(self.root / "simorgh_skills")
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))
        self.assertTrue(self.service._registry)  # noqa: SLF001 -- the builtins are still there

    async def test_a_registered_skill_is_offered_to_a_session(self):
        """A profile is a static tuple, so a `skill:` name could never
        appear in one; `offered_tools` has to add them."""
        from simorgh.orchestration.tools import forget_registered, note_registered, offered_tools

        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))
        self.addCleanup(forget_registered)
        note_registered("read_file")
        note_registered("skill:earlier")
        offered = offered_tools(("read_file", "apply_skill"))
        self.assertIn("read_file", offered)
        self.assertIn("skill:earlier", offered)
        # And `apply_skill` is STILL offered, though nothing announced
        # it. Registration adds skills to a profile and must never
        # subtract from it: the registered set is empty at boot, so an
        # intersection would have stripped every builtin from every
        # session the moment one skill registered (observer,
        # 2026-09-08).
        self.assertIn("apply_skill", offered)


class TestSkillAcquiredRegistersOnDemand(_ExecutionServiceTestCase):
    async def test_registers_a_skill_tool_and_publishes_tool_registered(self):
        # Written AFTER boot: this class is about the on-demand path.
        # A file that exists at boot is now loaded by the boot scan
        # instead (see TestSkillsOnDiskAreLoadedAtBoot).
        await self._answer_memory_retrieve_once("Greets someone by name.")
        await self._start()
        (self.root / "simorgh_skills" / "greet.py").write_text(_SKILL_SOURCE)

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
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))
        (self.root / "simorgh_skills" / "lonely.py").write_text(_SKILL_SOURCE)

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
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))
        (self.root / "simorgh_skills" / "twice.py").write_text(_SKILL_SOURCE)

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

    async def test_a_changed_source_on_reacquisition_replaces_the_stale_tool(self):
        # Live-caught (observer, 2026-09-08): `_load_skill` used to
        # early-return the already-registered `SkillTool` unconditionally
        # -- `apply_skill` writes a fixed skill's source to the SAME
        # `simorgh_skills/<name>.py` path and then re-publishes
        # `learn.skill.acquired` for it in the very same process
        # (`Service._on_approved`), expecting the fix to go live
        # immediately. Because `SkillTool` captures its `_source` string
        # once at construction and never re-reads the file, the stale
        # object kept running the pre-fix code until the next kernel
        # restart -- a self-applied bugfix was invisible in-process.
        await self._start(config=ExecutionConfig(repo_root=self.root, skill_lookup_timeout_s=0.05))
        path = self.root / "simorgh_skills" / "fixme.py"
        path.write_text('def run(name="world"):\n    return f"v1 {name}"\n')

        from simorgh.contracts.protocols import ToolContext
        tool_ctx = ToolContext(
            action_id="a1", task_id=None, scope={}, constraints={},
            data_dir=self.root, clock=self.clock, logger=None, ledger=None,
        )

        tool_v1 = await self.service._load_skill("fixme", path="simorgh_skills/fixme.py")  # noqa: SLF001
        self.assertIsNotNone(tool_v1)
        result_v1 = await tool_v1.run({"name": "sim"}, ctx=tool_ctx)
        self.assertIn("v1 sim", result_v1.output)

        # The file changes on disk (what `apply_skill` does), then the
        # SAME name is "acquired" again in this same process.
        path.write_text('def run(name="world"):\n    return f"v2 {name}"\n')
        tool_v2 = await self.service._load_skill("fixme", path="simorgh_skills/fixme.py")  # noqa: SLF001
        self.assertIsNotNone(tool_v2)
        result_v2 = await tool_v2.run({"name": "sim"}, ctx=tool_ctx)
        self.assertIn("v2 sim", result_v2.output, "STALE CACHE: still running the pre-fix skill source")

        # And the registry itself was actually replaced, not just the
        # local variable above -- the next real invocation through
        # `_on_approved` must also see v2.
        self.assertIs(self.service._registry["skill:fixme"], tool_v2)  # noqa: SLF001


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

    async def test_tool_registered_carries_a_marker_arg_key_for_a_single_field_schema(self):
        """Live-caught (`execution/mcp.py::mcp_single_arg_key`'s own
        docstring): before this, an MCP tool's `tool.registered` never
        carried `marker_arg_key` at all -- only a skill's did -- so
        `orchestration/tools.py::register_tool_policy` had nothing to
        record for a brand-new server, and every marker-driven call to
        it arrived as `{"argument": ...}` against a schema with no such
        property. A real end-to-end repro (a stub server requiring
        `expression`) failed with "missing required field 'expression'"
        until this fix."""
        server = McpServerConfig(name="calc", command="fake-calc")
        tools = [{"name": "calc", "description": "d",
                  "inputSchema": {"type": "object", "required": ["expression"],
                                   "properties": {"expression": {"type": "string"}}}}]
        seen: list[dict] = []
        real_publish = self.bus.publish

        async def _spy_publish(message):
            if message.type == topics.TOOL_REGISTERED:
                seen.append(message.payload)
            return await real_publish(message)

        with unittest.mock.patch("simorgh.execution.service.McpClient", lambda s: _FakeMcpClient(s, tools=tools)), \
             unittest.mock.patch.object(self.bus, "publish", side_effect=_spy_publish):
            await self._boot(config=ExecutionConfig(repo_root=self.root, mcp_servers=(server,)))
        payload = next(p for p in seen if p.get("name") == "mcp_calc_calc")
        self.assertEqual(payload.get("marker_arg_key"), "expression")

    async def test_tool_registered_omits_marker_arg_key_for_a_multi_field_schema(self):
        """The marker layer is genuinely single-argument -- a schema with
        more than one property has no single "raw text" slot to infer,
        so this stays `None` and needs a human's hand-written
        `_MARKER_ARG_KEY` entry, same as before this fix."""
        server = McpServerConfig(name="db", command="fake-db")
        tools = [{"name": "query", "description": "d",
                  "inputSchema": {"type": "object", "properties": {
                      "table": {"type": "string"}, "filter": {"type": "string"}}}}]
        seen: list[dict] = []
        real_publish = self.bus.publish

        async def _spy_publish(message):
            if message.type == topics.TOOL_REGISTERED:
                seen.append(message.payload)
            return await real_publish(message)

        with unittest.mock.patch("simorgh.execution.service.McpClient", lambda s: _FakeMcpClient(s, tools=tools)), \
             unittest.mock.patch.object(self.bus, "publish", side_effect=_spy_publish):
            await self._boot(config=ExecutionConfig(repo_root=self.root, mcp_servers=(server,)))
        payload = next(p for p in seen if p.get("name") == "mcp_db_query")
        self.assertIsNone(payload.get("marker_arg_key"))

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
