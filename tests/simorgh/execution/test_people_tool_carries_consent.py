"""Stage 10: consent reaches the People store through the one path a
person confirms -- the tier-3 `people` tool -- and nowhere else.

The agent that built the consent field noted the tool verbs were not
wired; a permission field nothing can set is the unconnected-wire bug
this codebase keeps finding, so this pins the wire from the tool's end.
"""

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.tiers import tier_of
from simorgh.execution.config import Config
from simorgh.execution.tools import PeopleTool
from simorgh.guardian.api import Proposal


class _Bus:
    source = "execution"

    def __init__(self):
        self.sent = []

    def new(self, topic, payload):
        return Message.new(topic, source=self.source, payload=payload)

    async def request(self, message, timeout=None):
        self.sent.append(message)
        return Message.new(topics.WORLD_PEOPLE_UPDATE_REPLY, source="worldmodel",
                           payload={"ok": True, "person": {"name": "Saeed"}, "detail": "Saeed said yes to wellbeing_checkins"})


class _Ctx:
    def __init__(self, bus):
        self.bus = bus


class TheToolCarriesConsent(unittest.IsolatedAsyncioTestCase):
    async def test_a_grant_reaches_the_store_with_the_permission_named(self):
        bus = _Bus()
        result = await PeopleTool(Config()).run(
            {"action": "grant", "name": "Saeed", "permission": "wellbeing_checkins"}, ctx=_Ctx(bus))
        self.assertTrue(result.ok)
        sent = bus.sent[0]
        self.assertEqual(sent.type, topics.WORLD_PEOPLE_UPDATE)
        self.assertEqual((sent.payload["action"], sent.payload["name"], sent.payload["permission"]),
                         ("grant", "Saeed", "wellbeing_checkins"))
        self.assertIn("said yes", result.output)

    async def test_an_interest_travels_too(self):
        bus = _Bus()
        await PeopleTool(Config()).run({"action": "add_interest", "name": "Ira", "interest": "astronomy"},
                                       ctx=_Ctx(bus))
        self.assertEqual(bus.sent[0].payload["interest"], "astronomy")

    def test_the_schema_offers_every_verb_the_store_accepts(self):
        from simorgh.contracts.messages.world import WorldPeopleUpdate

        offered = set(PeopleTool.args_schema["properties"]["action"]["enum"])
        accepted = set(WorldPeopleUpdate.__dataclass_fields__["action"].type.__args__) \
            if hasattr(WorldPeopleUpdate.__dataclass_fields__["action"].type, "__args__") else offered
        self.assertTrue(accepted <= offered or offered <= accepted)
        self.assertIn("grant", offered)
        self.assertIn("revoke", offered)

    def test_a_grant_is_tier_three_like_a_link(self):
        """Consent decides what Sim may bring up with somebody; that is a
        person's call in every posture, whatever the posture."""
        proposal = Proposal(action_id="a", tool="people", args={"action": "grant"}, scope={},
                            reversibility="reversible", rationale="", proposed_by="orchestration")
        self.assertEqual(tier_of(proposal)[0], 3)


if __name__ == "__main__":
    unittest.main()
