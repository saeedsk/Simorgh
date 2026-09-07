"""A plan session must be able to read.

Live-caught 2026-09-07, from the creator's log: repeated
`denied (policy): ['plan mode: only read-only tools']`. The tools being
denied were `list_dir` and `search_code` -- both read-only, and among the
only four a plan session is even offered.

The cause was one missing argument. `guardian/service.py` built its
`DecisionContext` without `tool=`, so `ctx.tool` was always `None`, and
`ModeRule`'s `read_only = bool(ctx.tool and ctx.tool.read_only)` was
therefore always `False`. Every tool looked like a writing tool. In plan
mode that denies everything, so a plan session could not read a single
file -- which is why all 20 of the creator's projects sat at `0/0 steps`:
nothing could ever produce a plan to decompose.
"""

from __future__ import annotations

import unittest

from simorgh.guardian.api import Config, DecisionContext, Proposal, ToolInfo
from simorgh.guardian.posture import Posture
from simorgh.guardian.rules import ModeRule


def _proposal(tool: str, reversibility: str, *, task_mode: str = "plan", origin: str = "curiosity") -> Proposal:
    return Proposal(
        action_id="a1", tool=tool, args={}, scope={}, reversibility=reversibility,
        rationale="step 1 of plan session", proposed_by="orchestration",
        task_id="t1", task_mode=task_mode, origin=origin,
    )


def _ctx(proposal: Proposal, *, mode: str = "guarded", posture: str = "guarded") -> DecisionContext:
    """The context Guardian's service builds -- including the `tool` it
    used to leave out."""
    return DecisionContext(
        now=0.0, system_state="running", posture=Posture(level=posture),
        config=Config(mode=mode),
        tool=ToolInfo(
            name=proposal.tool,
            read_only=proposal.reversibility == "read_only",
            reversibility=proposal.reversibility,
        ),
    )


class PlanModeTestCase(unittest.IsolatedAsyncioTestCase):
    async def _decide(self, proposal: Proposal, **kw):
        return await ModeRule().evaluate(proposal, _ctx(proposal, **kw))

    async def test_a_plan_session_may_read_a_file(self):
        decision = await self._decide(_proposal("read_file", "read_only"))
        self.assertEqual(decision.kind, "abstain")

    async def test_a_plan_session_may_list_a_directory(self):
        """`list_dir` was denied 22 times in the creator's real ledger."""
        decision = await self._decide(_proposal("list_dir", "read_only"))
        self.assertEqual(decision.kind, "abstain")

    async def test_a_plan_session_may_search_the_code(self):
        decision = await self._decide(_proposal("search_code", "read_only"))
        self.assertEqual(decision.kind, "abstain")

    async def test_a_plan_session_still_may_not_write(self):
        """The rule this was always meant to enforce, intact."""
        decision = await self._decide(_proposal("apply_source_patch", "reversible"))
        self.assertEqual(decision.kind, "deny")
        self.assertIn("plan mode: only read-only tools", decision.reasons)

    async def test_an_execute_session_may_write(self):
        decision = await self._decide(_proposal("apply_source_patch", "reversible", task_mode="execute"))
        self.assertEqual(decision.kind, "abstain")


class LockedModeTestCase(unittest.IsolatedAsyncioTestCase):
    """The same missing argument governed `locked`, where the rule also
    turns on read-only-ness. Locked is meant to leave reading alone."""

    async def _decide(self, proposal: Proposal, **kw):
        return await ModeRule().evaluate(proposal, _ctx(proposal, **kw))

    async def test_locked_still_allows_reading(self):
        decision = await self._decide(_proposal("read_file", "read_only", task_mode="execute"), mode="locked")
        self.assertEqual(decision.kind, "abstain")

    async def test_locked_denies_autonomous_writing(self):
        decision = await self._decide(
            _proposal("apply_source_patch", "reversible", task_mode="execute", origin="curiosity"), mode="locked",
        )
        self.assertEqual(decision.kind, "deny")

    async def test_observe_denies_everything_including_reads(self):
        """`observe` is the one mode where read-only is irrelevant, and
        that must not have changed."""
        decision = await self._decide(_proposal("read_file", "read_only", task_mode="execute"), mode="observe")
        self.assertEqual(decision.kind, "deny")


if __name__ == "__main__":
    unittest.main()
