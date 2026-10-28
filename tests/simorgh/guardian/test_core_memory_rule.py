"""`CoreMemoryRule` (corememory.py): whose core memory block an edit may touch.

Stage 15 item 8's plan: Guardian checks `memory_core_edit`'s `block`
against the proposal's requester -- a person's block only on behalf of that
same person who is one of the household (a guest edits no block, 2026-10-27), the household's by anyone in the household, never for a voice
Sim cannot place or from an outside (a2a) channel. Pinned against the real
`DEFAULT_PIPELINE`, so a denial here is the gate's answer, not one rule's.
"""

import unittest

import pytest

from simorgh.guardian.api import DecisionContext, Proposal, ToolInfo
from simorgh.guardian.config import Config
from simorgh.guardian.corememory import CoreMemoryRule
from simorgh.guardian.pipeline import Pipeline
from simorgh.guardian.posture import Posture
from simorgh.guardian.rules import DEFAULT_PIPELINE
from simorgh.guardian.service import _wire_layer

pytestmark = pytest.mark.contract


def _edit(block: str, *, requester: str = "", channel: str = "", tool: str = "memory_core_edit") -> Proposal:
    return Proposal(action_id="a1", tool=tool, args={"block": block, "old": "", "new": "prefers Farsi"}, scope={},
                    reversibility="reversible", rationale="test", proposed_by="orchestration",
                    requester=requester, requester_channel=channel)


def _ctx(role=None) -> DecisionContext:
    return DecisionContext(
        now=0.0, system_state="running", posture=Posture(level="guarded", baseline="guarded"),
        config=Config(irreversible_requires_human=False), role=role,
        tool=ToolInfo(name="memory_core_edit", read_only=False, reversibility="reversible", registered=True,
                      input_schema={"type": "object", "properties": {"block": {"type": "string"}},
                                    "required": ["block"]}),
    )


class CoreMemoryRuleTestCase(unittest.IsolatedAsyncioTestCase):
    async def decide(self, proposal: Proposal, ctx: DecisionContext | None = None):
        return await Pipeline(DEFAULT_PIPELINE).decide(proposal, ctx or _ctx())

    async def test_a_person_edits_their_own_block(self):
        for block in ("me", "Soodeh", "person:soodeh"):
            verdict = await self.decide(_edit(block, requester="Soodeh", channel="voice"))
            self.assertEqual(verdict.kind, "approved", (block, verdict))

    async def test_nobody_edits_another_persons_block(self):
        for block in ("Soodeh", "person:soodeh"):
            verdict = await self.decide(_edit(block, requester="Ira", channel="voice"))
            self.assertEqual(verdict.kind, "denied", block)
            self.assertEqual(verdict.layer, "core_memory")
            self.assertIn("not Ira's", " ".join(verdict.reasons))

    async def test_the_household_block_is_anyone_in_the_households(self):
        for requester in ("Saeed", "Soodeh", "Ira"):
            verdict = await self.decide(_edit("household", requester=requester, channel="voice"))
            self.assertEqual(verdict.kind, "approved", requester)

    async def test_a_named_visitor_may_not_edit_the_household_block(self):
        verdict = await self.decide(_edit("household", requester="Reza", channel="voice"))
        self.assertEqual(verdict.kind, "denied")
        self.assertIn("not one of the household", " ".join(verdict.reasons))

    async def test_a_named_visitor_may_not_edit_even_their_own_block(self):
        # The creator's choice, 2026-10-27: core blocks are the household's.
        for block in ("me", "Reza", "person:reza"):
            verdict = await self.decide(_edit(block, requester="Reza", channel="voice"))
            self.assertEqual(verdict.kind, "denied", block)
            self.assertEqual(verdict.layer, "core_memory")
            self.assertIn("not one of the household", " ".join(verdict.reasons))

    async def test_a_guest_by_the_people_store_may_not_edit_their_own_block(self):
        async def role(name):
            return "guest"

        verdict = await self.decide(_edit("me", requester="Soodeh", channel="voice"), _ctx(role))
        self.assertEqual(verdict.kind, "denied")

    async def test_the_people_stores_role_is_read_first(self):
        async def role(name):
            return "guest"

        verdict = await self.decide(_edit("household", requester="Soodeh", channel="voice"), _ctx(role))
        self.assertEqual(verdict.kind, "denied")

    async def test_an_unknown_speaker_is_denied(self):
        for requester, channel in (("unknown", "voice"), ("", "voice"), ("Guest", "voice")):
            for block in ("household", "me"):
                verdict = await self.decide(_edit(block, requester=requester, channel=channel))
                self.assertEqual(verdict.kind, "denied", (requester, block))
                self.assertEqual(verdict.layer, "core_memory")

    async def test_sims_own_idea_edits_nothing(self):
        verdict = await self.decide(_edit("household", requester="", channel="initiative"))
        self.assertEqual(verdict.kind, "denied")

    async def test_an_outside_channel_is_denied_whoever_it_names(self):
        for block in ("household", "me", "Saeed"):
            verdict = await self.decide(_edit(block, requester="Saeed", channel="a2a"))
            self.assertEqual(verdict.kind, "denied", block)
            self.assertIn("outside the house", " ".join(verdict.reasons))

    async def test_the_console_is_the_owners(self):
        for block in ("me", "household", "Saeed"):
            verdict = await self.decide(_edit(block, requester="", channel="cli"))
            self.assertEqual(verdict.kind, "approved", block)
        verdict = await self.decide(_edit("Soodeh", requester="", channel=""))
        self.assertEqual(verdict.kind, "denied")

    async def test_other_tools_are_not_its_business(self):
        decision = await CoreMemoryRule().evaluate(_edit("Soodeh", requester="Ira", tool="remember"), _ctx())
        self.assertEqual(decision.kind, "abstain")

    def test_the_denial_is_publishable(self):
        self.assertEqual(_wire_layer("core_memory"), "policy")


if __name__ == "__main__":
    unittest.main()
