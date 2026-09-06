"""The single most important test in `simorgh/curiosity/` (v1 milestones
95-96, docs/blueprint/subsystems/13-curiosity.md section 9): asking a
model one open-ended "propose an improvement" question, repeatedly,
clusters on the same neighborhood of ideas -- even reworded each time.
The fix is structural, not a better prompt: sample the target first, by
weighted randomness over a real inventory, before ever asking the model
anything. This test drives the real `Service` over a real (memory-backend)
Bus/Ledger through 10+ discovery ticks against a small fixed capability
map and asserts the sampler genuinely spreads exploration across every
module before repeating any of them -- not that it merely "sometimes"
avoids repeats.

Also covers two structural properties from the same lesson:
- a model reply that ignores "don't second-guess the target" and names a
  different file anyway still produces a candidate whose `subject` is the
  *originally sampled* target, never anything the model claims (S2).
- the milestone-96 OR-not-overwrite bug: when a tick's rare project
  attempt calls Cognition but produces no goal, and the tick then falls
  through to the per-target fallback (which may call Cognition again,
  or may not reach it at all), the tick's own `cognition_attempted`
  record must OR the two calls together rather than let the second
  silently overwrite whether the first one happened.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
import unittest
from pathlib import Path

_TARGET_LINE = re.compile(r"^Target: (.+)$", re.MULTILINE)

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.curiosity.config import Config as CuriosityConfig
from simorgh.curiosity.service import Service
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock

_AREAS = {
    "cognition": ["cognition/router.py", "cognition/prompts.py", "cognition/cache.py"],
    "memory": ["memory/store.py", "memory/consolidate.py"],
}
_ALL_MODULES = {m for mods in _AREAS.values() for m in mods}


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class RepetitionRegressionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="curiosity", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.ctx = Context(
            name="curiosity", instance_id="", run_id="regress", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.config = CuriosityConfig(candidates_per_tick=1, project_chance=0.0, recent_subjects=30)
        self.service = Service(config=self.config, seed=42)
        await self.service.start(self.ctx)

        self.requester = make_client(self.backend, source="test", ledger=self.ledger, clock=self.clock.now)
        await self.requester.start()
        self._world_sub = await self.requester.subscribe(topics.WORLD_ENV_QUERY, self._answer_world)
        self._gaps_sub = await self.requester.subscribe(topics.SELF_GAPS, self._answer_gaps)
        self._think_sub = await self.requester.subscribe(topics.COGNITION_THINK, self._answer_think_redirecting)
        self._redirect_target = "SOMEWHERE_ELSE.py"
        self._think_calls = 0

    async def asyncTearDown(self):
        await self._world_sub.unsubscribe()
        await self._gaps_sub.unsubscribe()
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
            payload = {"ok": True, "facet": "file_index", "as_of": self.clock.now(),
                       "path": args.get("path", ""), "available": True, "content": "x = 1\n",
                       "truncated": False, "total_chars": 6}
        else:
            payload = {"ok": False, "error": {"code": "unknown_facet", "detail": str(what), "retryable": False}}
        await self.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload=payload)

    async def _answer_gaps(self, message):
        await self.bus.reply(message, type=topics.SELF_GAPS_REPLY, payload={
            "ok": True, "version": 1, "gaps": [], "unexplored_areas": [],
        })

    async def _answer_think_redirecting(self, message):
        """A model reply that plausibly answers *and* explicitly tries to
        redirect to a different file -- spec scenario S2. Curiosity must
        never let this change which module the resulting candidate is
        filed against. Each description is a high-entropy hash of the
        real sampled target plus a call counter -- a fixed English
        template with only a word or two varying (e.g. "tidy up rough
        edge #N in <target>") would itself trip `RecentCandidates`'s own
        (real, separately unit-tested) near-duplicate dedupe across
        calls, since the large shared boilerplate dominates the
        similarity ratio regardless of target; that would be this test's
        fake responder breaking its own scenario, not a bug in the code
        under test."""
        self._think_calls += 1
        prompt = message.payload["messages"][0]["content"]
        match = _TARGET_LINE.search(prompt)
        real_target = match.group(1).strip() if match else "unknown"
        digest = hashlib.sha256(f"{self._think_calls}-{real_target}".encode()).hexdigest()[:24]
        text = (
            f"Actually, {self._redirect_target} matters more right now.\n"
            f"PATCH :: {digest}"
        )
        await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": text, "tool_calls": [], "provider": "fake", "cost_usd": 0.0,
            "tokens": 5, "floor": False, "non_answer": False,
        })

    async def _wait_until(self, predicate, *, timeout: float = 2.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() >= deadline:
                self.fail("timed out waiting for condition")
            await asyncio.sleep(0.01)

    async def _run_one_tick(self) -> dict:
        before = self.service._last_tick_record
        await self.bus.publish(self.bus.new(topics.SYSTEM_TICK_IDLE, {"idle_seconds": 5.0}))
        await self._wait_until(lambda: self.service._last_tick_record is not before)
        return self.service._last_tick_record

    # -- the central property -----------------------------------------------------------
    async def test_ten_ticks_never_repeat_a_module_before_every_module_is_tried(self):
        candidates = []
        sub = await self.requester.subscribe(topics.CURIOSITY_CANDIDATE, lambda m: candidates.append(m) or asyncio.sleep(0))
        try:
            for _ in range(12):
                await self._run_one_tick()
        finally:
            await sub.unsubscribe()

        subjects = [c.payload["subject"] for c in candidates]
        self.assertGreaterEqual(len(subjects), 10)
        for s in subjects:
            self.assertIn(s, _ALL_MODULES)

        # The actual claim: a module is never sampled a *second* time
        # until every module in the map has been sampled at least once.
        # Once that first full sweep completes, later repeats are
        # expected and fine (the point is "spread before repeating", not
        # "never repeat" -- a small fixed map is bound to repeat
        # eventually over enough ticks).
        seen: set[str] = set()
        for i, subject in enumerate(subjects):
            if subject in seen:
                self.assertEqual(
                    seen, _ALL_MODULES,
                    f"{subject!r} repeated at candidate {i} before every module in "
                    f"{_ALL_MODULES!r} had been tried once (seen so far: {seen!r})",
                )
            seen.add(subject)
        self.assertEqual(seen, _ALL_MODULES, "the run never covered every module even once")

    # -- S2: the model's own restated target is never trusted --------------------------
    async def test_model_redirect_is_ignored_subject_stays_the_sampled_target(self):
        candidates = []
        sub = await self.requester.subscribe(topics.CURIOSITY_CANDIDATE, lambda m: candidates.append(m) or asyncio.sleep(0))
        try:
            for _ in range(4):
                await self._run_one_tick()
        finally:
            await sub.unsubscribe()

        self.assertTrue(candidates)
        for c in candidates:
            self.assertIn(c.payload["subject"], _ALL_MODULES)
            self.assertNotEqual(c.payload["subject"], self._redirect_target)
            self.assertNotIn(self._redirect_target, c.payload["description"])

    # -- milestone-96: OR-not-overwrite across a project attempt + fallback ------------
    async def test_cognition_attempted_ors_across_project_attempt_and_fallback(self):
        """Force the rare project-proposal path to run (so it calls
        Cognition) and to fail to parse a goal (no `GOAL ::` line), which
        the real code path then falls through from into the normal
        per-target loop. `cognition_attempted` on the recorded tick must
        be True either way -- set once by the project attempt, never
        reset to False by whatever the fallback loop does afterward."""
        await self._think_sub.unsubscribe()

        async def answer_no_goal_then_patch(message):
            purpose = message.payload["purpose"]
            text = "I don't have a specific goal in mind right now." if purpose == "plan" else "PATCH :: small fix"
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": text, "tool_calls": [], "provider": "fake", "cost_usd": 0.0,
                "tokens": 5, "floor": False, "non_answer": False,
            })

        self._think_sub = await self.requester.subscribe(topics.COGNITION_THINK, answer_no_goal_then_patch)

        forced_cfg = CuriosityConfig(candidates_per_tick=1, project_chance=1.0)
        forced = Service(config=forced_cfg, seed=1)
        await forced.start(Context(
            name="curiosity2", instance_id="", run_id="regress2", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data2",
        ))
        try:
            await forced._run_tick(idle_seconds=5.0)
            tick = forced._last_tick_record
            self.assertNotIn("project", tick)  # the "no goal" reply must NOT be parsed as a project
            self.assertTrue(tick.get("cognition_attempted"))
        finally:
            await forced.stop()


if __name__ == "__main__":
    unittest.main()
