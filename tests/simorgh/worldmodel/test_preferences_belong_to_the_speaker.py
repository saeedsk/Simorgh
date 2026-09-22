"""Stage 6 item 4, the `persona/user_model.py` fold: a preference belongs
to the person who stated it.

Until 2026-09-22 "call me X" and "I prefer X" landed in ONE `user_profile`
facet for the whole household, and every chat prompt read it as "What you
know about the user" -- so a nickname Ira asked for was what Sim then
called her father. Now Persona names who said it, World Model files it in
that person's `preferences` in the People store, and the `user_profile`
query answers for one person only.

Run with the real Persona and World Model services on one bus, because
the bug lived in the join between them, not in either half.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.persona.config import Config as PersonaConfig
from simorgh.persona.service import Service as PersonaService
from simorgh.worldmodel.config import Config as WorldConfig
from simorgh.worldmodel.facets.people import PeopleFacet
from simorgh.worldmodel.service import Service as WorldService

from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class PreferencesBelongToTheSpeaker(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "repo"
        (root / "simorgh" / "memory").mkdir(parents=True)
        (root / "docs").mkdir()
        (root / "docs" / "SOUL.md").write_text("## Identity\n\nSimorgh is a test persona.\n")
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.data_dir = Path(self._tmp.name) / "data"
        self.clients = []
        self.world = WorldService(WorldConfig(repo_root=root))
        await self.world.start(await self._ctx("worldmodel"))
        self.persona = PersonaService(PersonaConfig(repo_root=root))
        await self.persona.start(await self._ctx("persona"))
        self.other = await self._client("interface")
        self.updates = []
        self._sub = await self.other.subscribe(topics.PERSONA_USER_MODEL_UPDATED,
                                               lambda m: self._record(m))

    async def _record(self, message):
        self.updates.append(message.payload)

    async def _client(self, source):
        client = make_client(self.backend, source=source, ledger=self.ledger, clock=self.clock.now)
        await client.start()
        self.clients.append(client)
        return client

    async def _ctx(self, name):
        return Context(name=name, instance_id="", run_id="test", mode="single", bus=await self._client(name),
                       ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Logger(),
                       data_dir=self.data_dir)

    async def asyncTearDown(self):
        await self._sub.unsubscribe()
        await self.persona.stop()
        await self.world.stop()
        for client in self.clients:
            await client.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _say(self, text, *, channel="voice", **who):
        await self.other.publish(self.other.new(topics.PERCEPT_TEXT_RECEIVED, {
            "channel": channel, "text": text, "session_id": "s1", **who}))
        for _ in range(5):
            await asyncio.sleep(0)

    def _prefs(self, name):
        return self.world._people.by_name(name).preferences

    async def _profile(self, **args):
        reply = await self.other.request(self.other.new(
            topics.WORLD_ENV_QUERY, {"what": "user_profile", "args": args}), timeout=2)
        self.assertTrue(reply.payload.get("ok"), reply.payload)
        return reply.payload

    # -- the acceptance ------------------------------------------------------------------
    async def test_iras_nickname_lands_on_ira_and_not_on_saeed(self):
        await self._say("call me Ira-bear", speaker="Ira")
        self.assertEqual(self._prefs("Ira")["preferred_name"]["value"], "Ira-bear")
        self.assertNotIn("preferred_name", self._prefs("Saeed"))
        # ...and it was written down, not only held in memory.
        on_disk = json.loads((self.data_dir / "people.json").read_text())
        ira = next(p for p in on_disk["people"] if p["name"] == "Ira")
        self.assertEqual(ira["preferences"]["preferred_name"]["value"], "Ira-bear")

    async def test_an_unknown_voice_lands_nowhere(self):
        before = {p.name: dict(p.preferences) for p in self.world._people.all()}
        await self._say("call me boss")                                   # an unplaced voice: no speaker
        await self._say("call me boss", speaker="Mallory")                # a name the store has no record of
        await self._say("call me Iris-cat", speaker="Iris", speaker_doubt="Ira sounds almost the same")
        await self._say("I prefer loud music", channel="api")             # a local surface naming nobody
        self.assertEqual({p.name: dict(p.preferences) for p in self.world._people.all()}, before)
        # Persona did not even publish the three it could not attribute.
        self.assertEqual([u.get("person") for u in self.updates], ["Mallory"])

    async def test_the_prompt_for_saeeds_turn_does_not_show_iras_preference(self):
        await self._say("call me Ira-bear", speaker="Ira")
        await self._say("I prefer short answers", channel="cli")         # the console is the owner's
        saeed = await self._profile(person="", channel="cli")
        self.assertEqual(saeed["person"], "Saeed")
        self.assertIn("short answers", saeed["text"])
        self.assertNotIn("Ira-bear", saeed["text"])
        self.assertNotIn("preferred_name", saeed["facets"])
        ira = await self._profile(person="Ira", channel="voice")
        self.assertIn("preferred_name: Ira-bear", ira["text"])
        self.assertNotIn("short answers", ira["text"])

    async def test_asked_without_saying_who_it_answers_nobody(self):
        """There is no household-wide "user" any more."""
        await self._say("call me Ira-bear", speaker="Ira")
        for args in ({}, {"person": ""}, {"person": "", "channel": "voice"}, {"person": "Stranger"}):
            answer = await self._profile(**args)
            self.assertIsNone(answer["person"], args)
            self.assertEqual(answer["text"], "", args)

    async def test_a_sentence_never_writes_a_permission(self):
        await self._say("I prefer wellbeing_checkins", speaker="Soodeh")
        await self.other.publish(self.other.new(topics.PERSONA_USER_MODEL_UPDATED, {
            "facet": "wellbeing_checkins", "value": True, "confidence": 1.0, "person": "Soodeh", "channel": "voice"}))
        await asyncio.sleep(0)
        soodeh = self.world._people.by_name("Soodeh")
        self.assertEqual(soodeh.permissions, ())
        self.assertNotIn("wellbeing_checkins", soodeh.preferences)
        self.assertEqual(soodeh.preferences["preference"]["value"], "wellbeing_checkins")

    async def test_a_payload_that_does_not_say_who_is_dropped(self):
        """How `persona.user_model.updated` looked before 2026-09-22 (and
        how a replay of `persona:user_model` looks): no person, no
        channel. Guessing the owner for it is the old bug."""
        await self.other.publish(self.other.new(topics.PERSONA_USER_MODEL_UPDATED, {
            "facet": "preferred_name", "value": "Al", "confidence": 0.7}))
        await asyncio.sleep(0)
        self.assertTrue(all(not p.preferences for p in self.world._people.all()))


class TheStore(unittest.TestCase):
    def setUp(self):
        self.people = PeopleFacet()

    def test_the_owner_is_the_console(self):
        self.assertEqual(self.people.speaker("", "cli").name, "Saeed")
        self.assertEqual(self.people.speaker("", "").name, "Saeed")
        self.assertIsNone(self.people.speaker("", "voice"))
        self.assertIsNone(self.people.speaker("", None))

    def test_a_linked_console_wins_over_the_role(self):
        self.people.link("Soodeh", "cli:owner")
        self.assertEqual(self.people.owner().name, "Soodeh")

    def test_a_low_confidence_preference_is_kept_but_not_told(self):
        ira = self.people.by_name("Ira")
        self.people.remember_preference(ira, "preference", "tea", 0.2)
        profile = self.people.profile(self.people.by_name("Ira"))
        self.assertIn("preference", profile["facets"])
        self.assertEqual(profile["text"], "")


if __name__ == "__main__":
    unittest.main()
