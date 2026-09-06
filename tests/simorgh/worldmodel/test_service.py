"""World Model Service, over a real (memory-backend) Bus/Ledger and a
real Context -- the same composition shape the Kernel uses, built by
hand here so this package's tests don't depend on `simorgh.kernel`
(boundary rule)."""

import tempfile
import unittest
from pathlib import Path

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.worldmodel.config import Config as WorldConfig
from simorgh.worldmodel.service import Service

from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class WorldModelTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmp.name) / "repo"
        (self.repo_root / "src" / "memory").mkdir(parents=True)
        (self.repo_root / "src" / "memory" / "long_term.py").write_text("X = 1\n")
        (self.repo_root / "docs").mkdir()
        (self.repo_root / "docs" / "SOUL.md").write_text("## Identity\n\nSimorgh is a test persona.\n")

        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="worldmodel", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()

        self.ctx = Context(
            name="worldmodel", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.service = Service(WorldConfig(repo_root=self.repo_root))
        await self.service.start(self.ctx)

        self.requester = make_client(backend, source="test", ledger=self.ledger, clock=self.clock.now)
        await self.requester.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.requester.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def test_capability_map_query_returns_real_areas(self):
        reply = await self.requester.request(
            self.requester.new(topics.WORLD_ENV_QUERY, {"what": "capability_map"}), timeout=2,
        )
        self.assertTrue(reply.payload["ok"])
        self.assertIn("memory", reply.payload["areas"])

    async def test_unknown_facet_is_an_honest_error(self):
        # `world.env.query`'s `what` field is a closed enum in the real
        # contract, so the bus client itself refuses an unrecognized
        # facet name before it can ever reach this handler -- there is
        # no reachable path to trigger this through a real request.
        # Exercised directly against the handler instead, as defense in
        # depth (e.g. a future facet name added here before its enum
        # entry lands, or a malformed message that slips past the
        # client-side check some other way).
        message = Message.new(topics.WORLD_ENV_QUERY, source="test", payload={"what": "not_a_real_facet"})
        replies = []

        async def _fake_reply(req, *, type, payload):
            replies.append(payload)

        self.service._ctx.bus.reply = _fake_reply
        await self.service._on_env_query(message)
        self.assertFalse(replies[0]["ok"])
        self.assertEqual(replies[0]["error"]["code"], "unknown_facet")

    async def test_git_state_degrades_honestly_outside_a_repo(self):
        reply = await self.requester.request(
            self.requester.new(topics.WORLD_ENV_QUERY, {"what": "git_state"}), timeout=5,
        )
        self.assertTrue(reply.payload["ok"])
        self.assertFalse(reply.payload["available"])  # not a git repo -- honest, not fabricated

    async def test_self_summary_includes_real_identity(self):
        reply = await self.requester.request(
            self.requester.new(topics.SELF_SUMMARY, {"budget_tokens": 300}), timeout=2,
        )
        self.assertTrue(reply.payload["ok"])
        self.assertIn("test persona", reply.payload["text"])

    async def test_self_summary_truncates_under_a_tiny_budget(self):
        full = await self.requester.request(
            self.requester.new(topics.SELF_SUMMARY, {"budget_tokens": 10_000}), timeout=2,
        )
        tiny = await self.requester.request(
            self.requester.new(topics.SELF_SUMMARY, {"budget_tokens": 1}), timeout=2,
        )
        self.assertLess(tiny.payload["tokens"], full.payload["tokens"])
        self.assertIn("[truncated:", tiny.payload["text"])

    async def test_self_gaps_is_honestly_empty_this_phase(self):
        reply = await self.requester.request(
            self.requester.new(topics.SELF_GAPS, {"k": 5}), timeout=2,
        )
        self.assertEqual(reply.payload["gaps"], [])

    async def test_self_md_rendered_to_disk(self):
        rendered = (self.ctx.data_dir / "self" / "SELF.md").read_text()
        self.assertIn("Simorgh", rendered)

    async def test_tool_registered_then_queried(self):
        await self.bus.publish(Message.new(
            topics.TOOL_REGISTERED, source="execution",
            payload={"name": "read_file", "version": "1", "description": "read a file", "read_only": True,
                     "reversibility": "read_only", "schema_ref": "blob:none", "provider": "builtin"},
        ))
        for _ in range(10):
            await __import__("asyncio").sleep(0)
        reply = await self.requester.request(
            self.requester.new(topics.WORLD_ENV_QUERY, {"what": "tools"}), timeout=2,
        )
        names = [t["name"] for t in reply.payload["tools"]]
        self.assertIn("read_file", names)

    async def test_health_ok(self):
        health = await self.service.health()
        self.assertEqual(health.status, "ok")


if __name__ == "__main__":
    unittest.main()
