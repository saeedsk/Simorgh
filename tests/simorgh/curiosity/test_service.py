"""Curiosity Service over a real (memory-backend) Bus/Ledger and Context
-- same composition shape as tests/simorgh/persona/test_service.py. World
Model and Cognition are faked here as plain request/reply responders on
the same bus (this package must not import their code -- module
boundary), so these tests exercise the real `request_or_error` /
graceful-degradation path, not mocks of `service.py`'s own internals."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.curiosity.config import Config as CuriosityConfig
from simorgh.curiosity.service import Service
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


_AREAS = {"cognition": ["a.py", "b.py"], "learning": ["c.py"]}


class CuriosityServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="curiosity", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()

        self.ctx = Context(
            name="curiosity", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.config = CuriosityConfig(candidates_per_tick=1, boredom_after_seconds=60.0, project_chance=0.0)
        self.service = Service(config=self.config, seed=7)
        await self.service.start(self.ctx)

        self.requester = make_client(self.backend, source="test", ledger=self.ledger, clock=self.clock.now)
        await self.requester.start()

        self._world_replies = []
        self._think_replies = []
        self._world_sub = await self.requester.subscribe(topics.WORLD_ENV_QUERY, self._answer_world)
        self._self_sub = await self.requester.subscribe(topics.SELF_GAPS, self._answer_gaps)
        self._think_sub = await self.requester.subscribe(topics.COGNITION_THINK, self._answer_think)

    async def asyncTearDown(self):
        await self._world_sub.unsubscribe()
        await self._self_sub.unsubscribe()
        await self._think_sub.unsubscribe()
        await self.service.stop()
        await self.requester.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _answer_world(self, message):
        what = message.payload.get("what")
        if what == "capability_map":
            payload = {"ok": True, "facet": "capability_map", "as_of": self.clock.now(),
                       "areas": list(_AREAS), "modules_by_area": dict(_AREAS)}
        elif what == "file_index":
            args = message.payload.get("args") or {}
            if args.get("path"):
                payload = {"ok": True, "facet": "file_index", "as_of": self.clock.now(),
                           "path": args["path"], "available": True, "content": "preview text", "truncated": False, "total_chars": 12}
            else:
                payload = {"ok": True, "facet": "file_index", "as_of": self.clock.now(),
                           "files": [{"path": p, "size": 1, "mtime": 0.0} for mods in _AREAS.values() for p in mods],
                           "truncated": False, "under": "src"}
        else:
            payload = {"ok": False, "error": {"code": "unknown_facet", "detail": what, "retryable": False}}
        await self.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload=payload)

    async def _answer_gaps(self, message):
        await self.bus.reply(message, type=topics.SELF_GAPS_REPLY, payload={
            "ok": True, "version": 1, "gaps": [], "unexplored_areas": [],
        })

    async def _answer_think(self, message):
        self._think_replies.append(message)
        purpose = message.payload["purpose"]
        if purpose == "plan":
            text = "GOAL :: build a real thing"
        else:
            text = "PATCH :: tighten a loop"
        await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": text, "tool_calls": [], "provider": "fake", "cost_usd": 0.0,
            "tokens": 10, "floor": False, "non_answer": False,
        })

    async def _pump(self, n: int = 20) -> None:
        for _ in range(n):
            await asyncio.sleep(0)

    async def _wait_until(self, predicate, *, timeout: float = 2.0) -> None:
        """Several chained request/reply round trips (world -> gaps ->
        preview -> think) need more event-loop turns than a fixed
        `sleep(0)` pump reliably provides; poll with real (short) sleeps
        instead of guessing an iteration count."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() >= deadline:
                self.fail("timed out waiting for condition")
            await asyncio.sleep(0.01)

    # -- tick gating ------------------------------------------------------------------
    async def test_tick_skipped_when_backlog_nonempty(self):
        await self.bus.publish(self.bus.new(topics.TASK_CREATED, {
            "task_id": "t1", "kind": "patch", "description": "x", "depends_on": [],
            "mode": "execute", "origin": "human", "risk": "low",
        }))
        await self._pump()
        seen = []
        sub = await self.requester.subscribe(topics.CURIOSITY_CANDIDATE, lambda m: seen.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.SYSTEM_TICK_IDLE, {"idle_seconds": 100.0}))
        await self._wait_until(lambda: bool(self.service._last_tick_record))
        await sub.unsubscribe()
        self.assertFalse(seen)
        self.assertEqual(self.service._last_tick_record.get("skipped_reason"), "backlog_nonempty")

    async def test_tick_produces_a_candidate_targeting_the_sampled_subject(self):
        seen = []
        sub = await self.requester.subscribe(topics.CURIOSITY_CANDIDATE, lambda m: seen.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.SYSTEM_TICK_IDLE, {"idle_seconds": 5.0}))
        await self._wait_until(lambda: len(seen) >= 1)
        await sub.unsubscribe()
        self.assertEqual(len(seen), 1)
        candidate = seen[0].payload
        self.assertEqual(candidate["kind"], "patch")
        self.assertIn(candidate["subject"], [p for mods in _AREAS.values() for p in mods])
        self.assertEqual(candidate["area"], "cognition" if candidate["subject"] in _AREAS["cognition"] else "learning")

    async def test_paused_state_skips_ticks(self):
        await self.bus.publish(self.bus.new(topics.SYSTEM_STATE_CHANGED, {"state": "paused"}))
        await self._pump()
        seen = []
        sub = await self.requester.subscribe(topics.CURIOSITY_CANDIDATE, lambda m: seen.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.SYSTEM_TICK_IDLE, {"idle_seconds": 5.0}))
        await self._pump()
        await sub.unsubscribe()
        self.assertFalse(seen)
        self.assertEqual(self.service._last_tick_record.get("skipped_reason"), "paused")

    async def test_a_second_idle_tick_while_first_still_running_is_skipped_not_queued(self):
        gate = asyncio.Event()

        async def slow_think(message):
            await gate.wait()
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": "PATCH :: x", "tool_calls": [], "provider": "fake", "cost_usd": 0.0,
                "tokens": 1, "floor": False, "non_answer": False,
            })

        await self._think_sub.unsubscribe()
        self._think_sub = await self.requester.subscribe(topics.COGNITION_THINK, slow_think)

        await self.bus.publish(self.bus.new(topics.SYSTEM_TICK_IDLE, {"idle_seconds": 5.0}))
        await self._pump(10)
        self.assertTrue(self.service._tick_lock.locked())
        await self.bus.publish(self.bus.new(topics.SYSTEM_TICK_IDLE, {"idle_seconds": 5.0}))
        await self._pump(10)
        self.assertEqual(self.service._last_tick_record.get("skipped_reason"), "already_running")
        gate.set()
        await self._pump(10)

    # -- discover / share request-reply ------------------------------------------------
    async def test_discover_request_forces_a_tick_and_returns_created_ids(self):
        reply = await self.requester.request(self.requester.new(topics.CURIOSITY_DISCOVER_REQUEST, {}), timeout=2)
        self.assertEqual(len(reply.payload["created"]), 1)

    async def test_share_request_growth_before_news(self):
        await self.bus.publish(self.bus.new(topics.LEARN_SKILL_ACQUIRED, {"name": "new_skill", "path": "x.py", "tests": 3}))
        await self._pump()
        reply = await self.requester.request(
            self.requester.new(topics.CURIOSITY_SHARE_REQUEST, {"kind": "growth"}), timeout=2,
        )
        self.assertTrue(reply.payload["shared"])
        self.assertTrue(reply.payload["content_ref"].startswith(f"{topics.LEARN_SKILL_ACQUIRED}:"))

    async def test_share_request_kind_mismatch_reports_not_shared(self):
        await self.bus.publish(self.bus.new(topics.LEARN_SKILL_ACQUIRED, {"name": "s", "path": "x.py", "tests": 1}))
        await self._pump()
        reply = await self.requester.request(
            self.requester.new(topics.CURIOSITY_SHARE_REQUEST, {"kind": "news"}), timeout=2,
        )
        self.assertFalse(reply.payload["shared"])
        self.assertNotIn("content_ref", reply.payload)

    # -- interests ----------------------------------------------------------------------
    async def test_interest_add_then_list(self):
        await self.bus.publish(self.bus.new(topics.CURIOSITY_INTEREST_ADD, {"topic": "quantum computing"}))
        await self._pump()
        reply = await self.requester.request(self.requester.new(topics.CURIOSITY_INTEREST_LIST_REQUEST, {}), timeout=2)
        topics_seen = [i["topic"] for i in reply.payload["interests"]]
        self.assertIn("quantum computing", topics_seen)
        # the three seeded defaults plus the one just added
        self.assertEqual(len(topics_seen), 4)

    async def test_follow_up_on_feed_url_proposes_a_web_fetch_action(self):
        seen = []
        sub = await self.requester.subscribe(topics.ACTION_PROPOSED, lambda m: seen.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.CURIOSITY_INTEREST_FOLLOW_UP_REQUEST, {"topic": "https://example.com/feed"}))
        await self._pump()
        await sub.unsubscribe()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].payload["tool"], "web_fetch")
        self.assertEqual(seen[0].payload["args"]["url"], "https://example.com/feed")

    async def test_action_result_completes_the_follow_up_and_stores_memory(self):
        rss = (
            "<rss version=\"2.0\"><channel>"
            "<item><title>Headline</title><description>Summary</description>"
            "<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>"
            "</channel></rss>"
        )
        action_id = "web_fetch-abc-1"
        self.service._pending_web_fetches[action_id] = "https://example.com/feed"
        stored = []
        sub = await self.requester.subscribe(topics.MEMORY_STORE, lambda m: stored.append(m) or asyncio.sleep(0))
        updated = []
        sub2 = await self.requester.subscribe(topics.CURIOSITY_INTEREST_UPDATED, lambda m: updated.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.ACTION_RESULT, {
            "action_id": action_id, "ok": True, "output_ref": "", "stdout_preview": rss,
            "duration_ms": 5, "side_effects": [],
        }))
        await self._pump()
        await sub.unsubscribe()
        await sub2.unsubscribe()
        self.assertEqual(len(stored), 1)
        self.assertIn("Headline", stored[0].payload["content"])
        self.assertEqual(updated[0].payload["items_found"], 1)

    async def test_action_denied_still_completes_the_follow_up(self):
        action_id = "web_fetch-abc-2"
        self.service._pending_web_fetches[action_id] = "https://example.com/feed"
        updated = []
        sub = await self.requester.subscribe(topics.CURIOSITY_INTEREST_UPDATED, lambda m: updated.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.ACTION_DENIED, {
            "action_id": action_id, "reasons": ["policy"], "layer": "policy",
        }))
        await self._pump()
        await sub.unsubscribe()
        self.assertEqual(updated[0].payload["items_found"], 0)

    # -- graceful degradation -----------------------------------------------------------
    async def test_missing_world_model_produces_no_crash_and_records_skip(self):
        await self._world_sub.unsubscribe()
        cfg = CuriosityConfig(candidates_per_tick=1, world_query_timeout=0.05, project_chance=0.0)
        svc = Service(config=cfg, seed=1)
        await svc.start(self.ctx.__class__(
            name="curiosity2", instance_id="", run_id="t2", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data2",
        ))
        await svc._run_tick(idle_seconds=5.0, force=True)
        self.assertEqual(svc._last_tick_record.get("skipped_reason"), "no_world_model")
        await svc.stop()


if __name__ == "__main__":
    unittest.main()
