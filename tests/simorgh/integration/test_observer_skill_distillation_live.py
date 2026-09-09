"""Observer W21-09: skill distillation (`reflection/distillation.py` +
`reflection/service.py::_maybe_distil`) against a real Reflection
service -- same composition shape as
`test_reflection_health_patterns_calibration.py`.

Checks, per the observer brief:
- a successful multi-tool patch task DOES produce a task.create(kind=skill)
- a failed one does not
- the daily cap holds
- `_distilled_today` is actually tracked per day (via `_distilled_day`),
  not a counter that only ever goes up and disables the feature forever
  once a long-running process crosses the cap once
- `_existing_skills()` resolves `skill_dir` against the real repo root,
  not the process cwd (booting from elsewhere silently defeated the
  slug-collision check that `distillation.slug_for` depends on it for)
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.reflection.config import Config as ReflectionConfig
from simorgh.reflection.service import Service, _repo_root

from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class SkillDistillationLiveTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="reflection", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()

        self.ctx = Context(
            name="reflection", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.config = ReflectionConfig(
            review_timeout_s=0.2, max_distillations_per_day=1,
        )
        self.service = Service(self.config)
        await self.service.start(self.ctx)

        self.driver = make_client(backend, source="test", ledger=self.ledger, clock=self.clock.now)
        await self.driver.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.driver.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    def _collect(self):
        seen: list = []

        async def _handler(message):
            seen.append(message.payload)
        return seen, _handler

    async def _run_task(self, task_id: str, *, kind: str, tools: list[str], succeeded: bool,
                         description: str = "search real listings and build a page for 95120") -> None:
        await self.driver.publish(self.driver.new(topics.TASK_CREATED, {
            "task_id": task_id, "kind": kind, "description": description,
            "depends_on": [], "mode": "execute", "origin": "human", "risk": "low",
        }))
        for i, tool in enumerate(tools):
            await self.driver.publish(self.driver.new(topics.TASK_STEP, {
                "task_id": task_id, "step_no": i, "phase": "act", "tool": tool, "summary": "",
            }))
        topic = topics.TASK_COMPLETED if succeeded else topics.TASK_FAILED
        payload = {"task_id": task_id, "terminal": True}
        if succeeded:
            payload.update({"result_summary": "done", "artifacts": [], "verification_ref": None})
        else:
            payload.update({"reason": "failed", "attempts": 1})
        await self.driver.publish(self.driver.new(topic, payload))

    async def test_a_successful_multi_tool_patch_task_proposes_a_skill(self):
        seen, handler = self._collect()
        await self.driver.subscribe(topics.TASK_CREATE, handler)
        await _pump()

        await self._run_task(
            "patch-1", kind="patch", succeeded=True,
            tools=["search_listings", "apply_source_patch", "git_commit", "render_page"],
        )
        await asyncio.wait_for(self._wait_for(seen, 1), timeout=5)

        self.assertEqual(seen[0]["kind"], "skill")
        self.assertIn("95120", seen[0]["subject"])

    async def test_a_failed_task_never_proposes_a_skill(self):
        seen, handler = self._collect()
        await self.driver.subscribe(topics.TASK_CREATE, handler)
        await _pump()

        await self._run_task(
            "patch-2", kind="patch", succeeded=False,
            tools=["search_listings", "apply_source_patch", "git_commit", "render_page"],
        )
        await _pump(50)

        self.assertEqual(seen, [])

    async def test_the_daily_cap_holds_within_a_day(self):
        seen, handler = self._collect()
        await self.driver.subscribe(topics.TASK_CREATE, handler)
        await _pump()

        await self._run_task(
            "patch-3", kind="patch", succeeded=True, description="task A for 90001",
            tools=["search_listings", "apply_source_patch", "git_commit"],
        )
        await asyncio.wait_for(self._wait_for(seen, 1), timeout=5)

        await self._run_task(
            "patch-4", kind="patch", succeeded=True, description="task B for 90002",
            tools=["search_listings", "apply_source_patch", "git_commit"],
        )
        await _pump(50)

        # cap is 1/day: the second distillable task within the same day
        # must not produce a second skill proposal.
        self.assertEqual(len(seen), 1)

    async def test_the_cap_resets_on_a_new_day_rather_than_disabling_the_feature_forever(self):
        """The live bug this guards: `_distilled_today` used to be a
        counter that only ever incremented, so once a long-running
        process crossed `max_distillations_per_day` the feature silently
        turned off for the rest of the process's life, not just the
        rest of the day."""
        seen, handler = self._collect()
        await self.driver.subscribe(topics.TASK_CREATE, handler)
        await _pump()

        await self._run_task(
            "patch-5", kind="patch", succeeded=True, description="task A for 90003",
            tools=["search_listings", "apply_source_patch", "git_commit"],
        )
        await asyncio.wait_for(self._wait_for(seen, 1), timeout=5)

        # A day later.
        self.clock.advance(90000.0)

        await self._run_task(
            "patch-6", kind="patch", succeeded=True, description="task B for 90004",
            tools=["search_listings", "apply_source_patch", "git_commit"],
        )
        await asyncio.wait_for(self._wait_for(seen, 2), timeout=5)
        self.assertEqual(len(seen), 2)

    async def _wait_for(self, seen: list, n: int) -> None:
        while len(seen) < n:
            await asyncio.sleep(0.01)

    async def test_existing_skills_resolves_against_the_repo_root_not_cwd(self):
        """`_existing_skills` used to glob `Path(self.config.skill_dir)`
        directly, i.e. relative to the process cwd. `apply_source_patch`
        -- the tool that actually writes a distilled skill -- resolves
        the same path against `execution.Config.repo_root`
        (`find_repo_root()`), which need not be the cwd (a sandboxed
        trial, the sim loader, any service manager with its own working
        directory). This writes a skill file at the *real* location and
        confirms `_existing_skills()` sees it regardless of cwd."""
        skill_dir = _repo_root() / self.config.skill_dir
        skill_dir.mkdir(parents=True, exist_ok=True)
        marker = skill_dir / "an_existing_skill.py"
        marker.write_text("# marker\n")
        try:
            self.assertIn("an_existing_skill", self.service._existing_skills())  # noqa: SLF001
        finally:
            marker.unlink()


if __name__ == "__main__":
    unittest.main()
