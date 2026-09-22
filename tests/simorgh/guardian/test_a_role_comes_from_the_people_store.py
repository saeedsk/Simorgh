"""A role set in the People store is the role Guardian decides with
(stage 6 items 4-5).

`people set_role` is a tier-3 action a person confirms, and until
2026-09-22 it changed nothing Guardian did: `PersonRule` read roles only
from `contracts/household.py`. A guest made an adult was still a guest.
"""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace

from simorgh.guardian.api import DecisionContext, Proposal, ToolInfo
from simorgh.guardian.config import Config
from simorgh.guardian.posture import Posture
from simorgh.guardian.tiers import PersonRule


def _proposal(requester: str) -> Proposal:
    return Proposal(action_id="a1", tool="git_commit", args={}, scope={}, reversibility="irreversible",
                    rationale="", proposed_by="orchestration", requester=requester, requester_channel="voice")


def _ctx(store: dict[str, str] | None) -> DecisionContext:
    async def role(person: str):
        return None if store is None else store.get(person)

    return DecisionContext(now=0.0, system_state="running", posture=Posture(level="guarded"),
                           config=Config(mode="guarded"),
                           tool=ToolInfo(name="git_commit", reversibility="irreversible", read_only=False),
                           role=role)


def _decide(requester: str, store: dict[str, str] | None) -> str:
    return asyncio.run(PersonRule().evaluate(_proposal(requester), _ctx(store))).kind


class TheStoreDecides(unittest.TestCase):
    def test_a_guest_made_an_adult_is_an_adult(self):
        self.assertEqual(_decide("Bobby", None), "escalate", "a guest, by the household file")
        self.assertEqual(_decide("Bobby", {"Bobby": "adult"}), "abstain")

    def test_a_child_lowered_to_guest_does_not_keep_more(self):
        self.assertEqual(_decide("Soodeh", {"Soodeh": "guest"}), "escalate")

    def test_no_record_falls_back_to_the_household_file(self):
        self.assertEqual(_decide("Soodeh", {}), "abstain")
        self.assertEqual(_decide("Ira", {}), "escalate")

    def test_an_unknown_role_in_the_store_is_refused(self):
        self.assertEqual(_decide("Soodeh", {"Soodeh": "unknown"}), "deny")


if __name__ == "__main__":
    unittest.main()
