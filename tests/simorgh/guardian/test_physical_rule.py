"""`PhysicalRule` (rules.py): the house has its own gate.

The drill the 2026-09-18 evaluation asked for (S1/S6/S8): a proposal to
unlock a door, LABELLED `reversible` by its proposer and arriving while
`irreversible_requires_human` is False (the Kernel's live default), must
still reach a person. Pinned here against the real `DEFAULT_PIPELINE`,
not a stub, so the ordering of the rules is part of what is tested.
"""

import unittest

import pytest

from simorgh.guardian.api import DecisionContext, Proposal, ToolInfo
from simorgh.guardian.config import Config
from simorgh.guardian.pipeline import Pipeline
from simorgh.guardian.posture import Posture
from simorgh.guardian.rules import DEFAULT_PIPELINE, PhysicalRule

pytestmark = pytest.mark.contract


def _proposal(tool: str, args: dict | None = None, *, reversibility: str = "reversible") -> Proposal:
    return Proposal(action_id="a1", tool=tool, args=args or {}, scope={}, reversibility=reversibility,
                    rationale="test", proposed_by="test")


def _ctx(config: Config | None = None, *, level: str = "guarded") -> DecisionContext:
    config = config or Config(irreversible_requires_human=False)  # the live default
    return DecisionContext(
        now=0.0, system_state="running", posture=Posture(level=level, baseline="guarded"),
        config=config,
    )


def _with_tool(ctx: DecisionContext, proposal: Proposal) -> DecisionContext:
    # Mirrors guardian/service.py: ToolInfo is built from the proposal's own label.
    return DecisionContext(
        now=ctx.now, system_state=ctx.system_state, posture=ctx.posture, config=ctx.config,
        tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only",
                      reversibility=proposal.reversibility),
    )


class TheDrill(unittest.IsolatedAsyncioTestCase):
    """A mislabelled unlock is escalated by the real pipeline."""

    async def test_unlock_labelled_reversible_still_needs_a_person(self):
        pipeline = Pipeline(DEFAULT_PIPELINE)
        proposal = _proposal("home_call", {"service": "lock.unlock", "target": "lock.front_door"},
                             reversibility="reversible")
        verdict = await pipeline.decide(proposal, _with_tool(_ctx(), proposal))
        self.assertEqual(verdict.kind, "needs_human")
        self.assertEqual(verdict.layer, "physical")
        self.assertIn("lock.unlock", " ".join(verdict.reasons))

    async def test_a_siren_labelled_reversible_still_needs_a_person(self):
        pipeline = Pipeline(DEFAULT_PIPELINE)
        for tool in ("cam_siren", "ring_siren"):
            proposal = _proposal(tool, {"camera": "driveway"}, reversibility="reversible")
            verdict = await pipeline.decide(proposal, _with_tool(_ctx(), proposal))
            self.assertEqual(verdict.kind, "needs_human", tool)

    async def test_trusted_mode_does_not_bypass_the_house(self):
        pipeline = Pipeline(DEFAULT_PIPELINE)
        cfg = Config(mode="trusted", irreversible_requires_human=False)
        proposal = _proposal("home_call", {"service": "alarm_control_panel.alarm_disarm", "target": "alarm.house"})
        verdict = await pipeline.decide(proposal, _with_tool(_ctx(cfg), proposal))
        self.assertEqual(verdict.kind, "needs_human")


class WhatStaysRoutine(unittest.IsolatedAsyncioTestCase):
    async def test_a_light_is_approved_in_guarded(self):
        pipeline = Pipeline(DEFAULT_PIPELINE)
        proposal = _proposal("home_call", {"service": "light.turn_on", "target": "light.kitchen"})
        verdict = await pipeline.decide(proposal, _with_tool(_ctx(), proposal))
        self.assertEqual(verdict.kind, "approved")

    async def test_the_tv_and_a_camera_light_are_approved(self):
        pipeline = Pipeline(DEFAULT_PIPELINE)
        for tool, args in (("cast_play", {"url": "x"}), ("tv_key", {"key": "next"}), ("cam_light", {"camera": "d", "on": True})):
            proposal = _proposal(tool, args)
            verdict = await pipeline.decide(proposal, _with_tool(_ctx(), proposal))
            self.assertEqual(verdict.kind, "approved", tool)

    async def test_observing_the_house_is_not_a_physical_action(self):
        rule = PhysicalRule()
        for tool in ("cam_list", "cam_snapshot", "ring_live", "home_state", "energy_report"):
            decision = await rule.evaluate(_proposal(tool, reversibility="read_only"), _ctx())
            self.assertEqual(decision.kind, "abstain", tool)

    async def test_a_code_tool_is_none_of_this_rules_business(self):
        rule = PhysicalRule()
        decision = await rule.evaluate(_proposal("apply_source_patch", {"path": "simorgh/x.py"},
                                                 reversibility="irreversible"), _ctx())
        self.assertEqual(decision.kind, "abstain")


class LockedAndTheSwitch(unittest.IsolatedAsyncioTestCase):
    async def test_locked_denies_every_physical_action(self):
        rule = PhysicalRule()
        ctx = _ctx(level="locked")
        for tool, args in (("home_call", {"service": "light.turn_on", "target": "light.k"}), ("tv_key", {"key": "up"})):
            decision = await rule.evaluate(_proposal(tool, args), ctx)
            self.assertEqual(decision.kind, "deny", tool)

    async def test_the_physical_switch_is_the_only_way_through(self):
        pipeline = Pipeline(DEFAULT_PIPELINE)
        cfg = Config(irreversible_requires_human=False, physical_auto_approve=True)
        proposal = _proposal("home_call", {"service": "lock.unlock", "target": "lock.front_door"})
        verdict = await pipeline.decide(proposal, _with_tool(_ctx(cfg), proposal))
        self.assertEqual(verdict.kind, "approved")
        self.assertTrue(any("auto-approved by [guardian.physical]" in n for n in verdict.notes))


class TheConfigTable(unittest.TestCase):
    def test_physical_is_its_own_table(self):
        cfg = Config.from_mapping({"irreversible_requires_human": False,
                                   "physical": {"auto_approve": True, "always_human_tools": ["cam_siren"]}})
        self.assertTrue(cfg.physical_auto_approve)
        self.assertEqual(cfg.physical_always_human_tools, ("cam_siren",))
        self.assertFalse(cfg.irreversible_requires_human)

    def test_the_code_switch_does_not_reach_the_house(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"SIMORGH_GUARDIAN_AUTO_APPROVE": "1"}):
            cfg = Config.from_mapping({})
        self.assertFalse(cfg.irreversible_requires_human)
        self.assertFalse(cfg.physical_auto_approve)

    def test_defaults_are_pessimistic(self):
        cfg = Config()
        self.assertFalse(cfg.physical_auto_approve)
        self.assertIn("cam_siren", cfg.physical_always_human_tools)
        self.assertIn("home_", cfg.physical_tool_prefixes)


class InstallingASkillAlwaysAsks(unittest.IsolatedAsyncioTestCase):
    """`apply_skill` installs persistent code that later runs outside any
    worktree or test gate (2026-09-18 evaluation, S4)."""

    async def test_a_skill_install_reaches_a_person_even_in_trusted_mode(self):
        pipeline = Pipeline(DEFAULT_PIPELINE)
        for cfg in (Config(irreversible_requires_human=False), Config(mode="trusted", irreversible_requires_human=False)):
            proposal = _proposal("apply_skill", {"name": "weather", "code": "def run(a):\n    return a\n"},
                                 reversibility="reversible")
            verdict = await pipeline.decide(proposal, _with_tool(_ctx(cfg), proposal))
            self.assertEqual(verdict.kind, "needs_human", cfg.mode)
            self.assertEqual(verdict.layer, "human_only")

    async def test_the_list_is_the_switch(self):
        pipeline = Pipeline(DEFAULT_PIPELINE)
        cfg = Config.from_mapping({"irreversible_requires_human": False, "human_only_tools": []})
        proposal = _proposal("apply_skill", {"name": "weather", "code": "def run(a):\n    return a\n"})
        verdict = await pipeline.decide(proposal, _with_tool(_ctx(cfg), proposal))
        self.assertEqual(verdict.kind, "approved")
