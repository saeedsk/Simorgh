"""Stage 6 item 4: one identity per person across every channel, so what
Ira says in the kitchen is found under her name on Telegram -- and a
person Sim cannot place stays unknown rather than becoming somebody new."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.people import Person, household_people, normalise_identity
from simorgh.worldmodel.facets.people import PeopleFacet


class TheStore(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "people.json"
        self.addCleanup(self.tmp.cleanup)

    def test_a_fresh_install_knows_the_family(self):
        people = PeopleFacet(self.path)
        names = {p.name: p.role for p in people.all()}
        self.assertEqual(names["Saeed"], "owner")
        self.assertEqual(names["Ira"], "child")
        self.assertEqual(names["Soodeh"], "adult")
        self.assertTrue(self.path.is_file(), "and writes it down")

    def test_one_person_across_channels(self):
        people = PeopleFacet(self.path)
        people.link("Saeed", "telegram:@Saeed")
        self.assertEqual(people.resolve("telegram:saeed").name, "Saeed")
        self.assertEqual(people.resolve("voice:Saeed").name, "Saeed")
        self.assertEqual(people.resolve("voice:Saeed").namespace, "person:Saeed",
                         "one namespace, so the kitchen and Telegram share a memory")

    def test_an_unlinked_identity_is_nobody(self):
        people = PeopleFacet(self.path)
        self.assertIsNone(people.resolve("whatsapp:14155550123"))
        self.assertEqual(people.role_of("whatsapp:14155550123"), "unknown")
        self.assertIsNone(people.resolve("nonsense"))

    def test_a_guest_can_be_linked_and_promoted(self):
        people = PeopleFacet(self.path)
        people.link("Bobby", "voice:bobby")
        self.assertEqual(people.role_of("voice:bobby"), "guest")
        people.set_role("Bobby", "adult")
        self.assertEqual(people.role_of("voice:bobby"), "adult")
        people.unlink("voice:bobby")
        self.assertIsNone(people.resolve("voice:bobby"))

    def test_it_survives_a_restart_and_a_broken_file(self):
        PeopleFacet(self.path).link("Bobby", "telegram:bobby")
        self.assertEqual(PeopleFacet(self.path).resolve("telegram:bobby").name, "Bobby")
        self.path.write_text("{not json")
        self.assertTrue(PeopleFacet(self.path).by_name("Saeed"), "an unreadable file is not a reason to forget")

    async def test_the_query_shape(self):
        people = PeopleFacet(self.path)
        answer = await people.get({"identity": "voice:Ira"})
        self.assertEqual(answer["role"], "child")
        self.assertEqual(len((await people.get({}))["people"]), len(household_people()))


class Identities(unittest.TestCase):
    def test_one_spelling_per_identity(self):
        self.assertEqual(normalise_identity("Telegram:@Saeed"), "telegram:saeed")
        self.assertEqual(normalise_identity("whatsapp:+1 (415) 555-0123"), "whatsapp:14155550123")
        self.assertEqual(normalise_identity("nonsense:x"), "", "an unknown kind is not an identity")

    def test_a_person_round_trips(self):
        person = Person(person_id="x", name="X", role="guest").with_identity("voice:x")
        self.assertEqual(json.loads(json.dumps(person.to_dict()))["identities"], ["voice:x"])


if __name__ == "__main__":
    unittest.main()
