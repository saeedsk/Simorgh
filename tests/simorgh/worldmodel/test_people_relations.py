"""Stage 15 follow-up: a person's kin by name (`Person.relations`), written
through the one confirmed write (`world.people.update{set_relation}`),
kept in `people.json`, and answered by the `people` query Memory reads to
resolve "my son". The record's own rules are `tests/simorgh/contracts/
test_people_relations.py`."""

from __future__ import annotations

import json
import unittest

from simorgh.worldmodel.facets.people import PeopleFacet

# The module, not its TestCase: a TestCase imported by name would run its
# tests a second time from here.
from tests.simorgh.worldmodel import test_people_consent as _consent


class RelationsOverTheBus(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = _consent.ConsentOverTheBus.asyncSetUp
    asyncTearDown = _consent.ConsentOverTheBus.asyncTearDown
    _update = _consent.ConsentOverTheBus._update
    _person = _consent.ConsentOverTheBus._person

    async def test_set_relation_lands_on_the_record_and_on_disk(self):
        reply = await self._update(action="set_relation", name="Saeed", relation="son", other="Aran")
        self.assertTrue(reply["ok"], reply)
        self.assertIn("son is Aran", reply["detail"])
        self.assertEqual((await self._person("Saeed"))["relations"], {"son": "Aran"})
        on_disk = json.loads((self.data_dir / "people.json").read_text())
        saeed = next(p for p in on_disk["people"] if p["name"] == "Saeed")
        self.assertEqual(saeed["relations"], {"son": "Aran"})
        store = PeopleFacet(self.data_dir / "people.json")
        self.assertEqual(store.by_name("Saeed").relation("son"), "Aran", "survives a restart")

    async def test_an_empty_other_forgets_it(self):
        await self._update(action="set_relation", name="Saeed", relation="son", other="Aran")
        reply = await self._update(action="set_relation", name="Saeed", relation="son", other="")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual((await self._person("Saeed"))["relations"], {})

    async def test_a_relation_for_nobody_or_of_nothing_is_refused(self):
        reply = await self._update(action="set_relation", name="Kian", relation="son", other="Aran")
        self.assertFalse(reply["ok"])
        reply = await self._update(action="set_relation", name="Saeed", relation="", other="Aran")
        self.assertFalse(reply["ok"])
