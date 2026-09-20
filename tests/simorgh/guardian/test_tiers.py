"""Stage 6 item 5: how far an action reaches (tier 0-3), and who may reach
that far. A house has children in it; "unlock the front door" asked by a
nine-year-old is the failure this exists for."""

from __future__ import annotations

import unittest

from simorgh.guardian.api import DecisionContext, Proposal, ToolInfo
from simorgh.guardian.config import Config
from simorgh.guardian.posture import Posture
from simorgh.guardian.tiers import CEILING, PersonRule, TierRule, role_of, tier_of


def _proposal(tool: str, *, requester: str = "", channel: str = "", reversibility: str = "irreversible",
              args: dict | None = None) -> Proposal:
    return Proposal(action_id="a1", tool=tool, args=args or {}, scope={}, reversibility=reversibility,
                    rationale="", proposed_by="orchestration", requester=requester, requester_channel=channel)


def _ctx(tool: ToolInfo | None = None, *, mode: str = "guarded", level: str = "guarded") -> DecisionContext:
    return DecisionContext(now=0.0, system_state="running", posture=Posture(level=level),
                           config=Config(mode=mode), tool=tool)


class Tiers(unittest.TestCase):
    def test_the_tier_comes_from_what_the_tool_is(self):
        self.assertEqual(tier_of(_proposal("read_file", reversibility="read_only"))[0], 0)
        self.assertEqual(tier_of(_proposal("home_call", reversibility="reversible"))[0], 1)
        self.assertEqual(tier_of(_proposal("git_commit"))[0], 2)
        self.assertEqual(tier_of(_proposal("notify"))[0], 3)
        self.assertEqual(tier_of(_proposal("cam_siren", reversibility="reversible"))[0], 3,
                         "a siren is loud outside, whatever its class")

    def test_the_registry_wins_over_the_proposers_claim(self):
        """Evaluation S6: a proposal that calls run_shell read_only is not."""
        claim = _proposal("run_shell", reversibility="read_only")
        self.assertEqual(tier_of(claim, ToolInfo(name="run_shell", reversibility="irreversible", read_only=False))[0], 2)

    def test_an_irreversible_networked_tool_is_not_assumed_local(self):
        tier, why = tier_of(_proposal("some_new_tool"), network=True)
        self.assertEqual(tier, 3)
        self.assertIn("network", why)


class Roles(unittest.TestCase):
    def test_the_console_is_the_owners_and_a_stranger_is_unknown(self):
        self.assertEqual(role_of("", channel=""), "owner")
        self.assertEqual(role_of("", channel="voice"), "unknown")
        self.assertEqual(role_of("Saeed", channel="voice"), "owner")
        self.assertEqual(role_of("Soodeh", channel="voice"), "adult")
        self.assertEqual(role_of("Ira", channel="voice"), "child")
        self.assertEqual(role_of("Bobby", channel="voice"), "guest")

    def test_the_ceiling_refuses_upward(self):
        self.assertLess(CEILING["child"], CEILING["adult"])
        self.assertEqual(CEILING["unknown"], 0)


class WhoMayAsk(unittest.IsolatedAsyncioTestCase):
    async def test_a_child_asking_to_unlock_goes_to_an_adult(self):
        unlock = _proposal("home_call", requester="Ira", channel="voice", reversibility="irreversible",
                           args={"service": "lock.unlock", "target": "lock.front_door"})
        decision = await PersonRule().evaluate(unlock, _ctx())
        self.assertEqual(decision.kind, "escalate")
        self.assertIn("Ira is a child", decision.reasons[0])

    async def test_a_voice_sim_cannot_place_is_refused(self):
        decision = await PersonRule().evaluate(
            _proposal("home_call", channel="voice", reversibility="reversible"), _ctx())
        self.assertEqual(decision.kind, "deny")
        self.assertIn("cannot place", decision.reasons[0])

    async def test_a_child_may_still_turn_a_light_on(self):
        light = _proposal("home_call", requester="Ira", channel="voice", reversibility="reversible",
                          args={"service": "light.turn_on", "target": "light.kitchen"})
        self.assertEqual((await PersonRule().evaluate(light, _ctx())).kind, "abstain")

    async def test_an_adult_is_not_stopped_by_this_rule(self):
        commit = _proposal("git_commit", requester="Saeed", channel="voice")
        self.assertEqual((await PersonRule().evaluate(commit, _ctx())).kind, "abstain")


class TierThreeNeedsAPerson(unittest.IsolatedAsyncioTestCase):
    async def test_it_escalates_in_every_posture_and_denies_when_locked(self):
        notify = _proposal("notify", requester="Saeed")
        self.assertEqual((await TierRule().evaluate(notify, _ctx())).kind, "escalate")
        self.assertEqual((await TierRule().evaluate(notify, _ctx(mode="trusted"))).kind, "escalate",
                         "trusted is not consent to message somebody else")
        self.assertEqual((await TierRule().evaluate(notify, _ctx(level="locked"))).kind, "deny")

    async def test_local_work_is_left_to_the_ordinary_rules(self):
        self.assertEqual((await TierRule().evaluate(_proposal("git_commit"), _ctx())).kind, "abstain")


if __name__ == "__main__":
    unittest.main()
