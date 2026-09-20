"""Stage 10 item 1, over the bus: a grant arrives as `world.people.update`
(tier 3 on the way in, so a person confirmed it), lands on the record, and
a permission that does not exist is a refusal, not a silent no-op."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
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


class ConsentOverTheBus(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "repo"
        (root / "simorgh" / "memory").mkdir(parents=True)
        (root / "docs").mkdir()
        (root / "docs" / "SOUL.md").write_text("## Identity\n\nSimorgh is a test persona.\n")
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="worldmodel", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.data_dir = Path(self._tmp.name) / "data"
        self.ctx = Context(name="worldmodel", instance_id="", run_id="test", mode="single", bus=self.bus,
                           ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Logger(),
                           data_dir=self.data_dir)
        self.service = Service(WorldConfig(repo_root=root))
        await self.service.start(self.ctx)
        self.requester = make_client(backend, source="execution", ledger=self.ledger, clock=self.clock.now)
        await self.requester.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.requester.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _update(self, **payload):
        return (await self.requester.request(self.requester.new(topics.WORLD_PEOPLE_UPDATE, payload), timeout=2)).payload

    async def _person(self, name):
        reply = await self.requester.request(
            self.requester.new(topics.WORLD_ENV_QUERY, {"what": "people", "args": {"name": name}}), timeout=2)
        return reply.payload["person"]

    async def test_a_grant_lands_on_the_record_and_on_disk(self):
        reply = await self._update(action="grant", name="Soodeh", permission="wellbeing_checkins")
        self.assertTrue(reply["ok"], reply)
        self.assertIn("said yes", reply["detail"])
        self.assertEqual((await self._person("Soodeh"))["permissions"], ["wellbeing_checkins"])
        self.assertIn('"wellbeing_checkins"', (self.data_dir / "people.json").read_text())

    async def test_a_revoke_takes_it_back(self):
        await self._update(action="grant", name="Soodeh", permission="interest_shares")
        reply = await self._update(action="revoke", name="Soodeh", permission="interest_shares")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual((await self._person("Soodeh"))["permissions"], [])

    async def test_a_permission_that_does_not_exist_is_refused(self):
        reply = await self._update(action="grant", name="Soodeh", permission="mind_reading")
        self.assertIs(reply.get("ok"), False)
        self.assertIn("not a permission", reply["error"]["detail"])
        self.assertEqual((await self._person("Soodeh"))["permissions"], [])

    async def test_a_grant_to_nobody_is_refused(self):
        reply = await self._update(action="grant", name="Nobody", permission="wellbeing_checkins")
        self.assertIs(reply.get("ok"), False)
        self.assertIn("do not know", reply["error"]["detail"])

    async def test_an_interest_is_added_and_read_back(self):
        reply = await self._update(action="add_interest", name="Aran", interest="Lego Robotics")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual((await self._person("Aran"))["interests"], ["lego robotics"])
        await self._update(action="remove_interest", name="Aran", interest="lego robotics")
        self.assertEqual((await self._person("Aran"))["interests"], [])


if __name__ == "__main__":
    unittest.main()
