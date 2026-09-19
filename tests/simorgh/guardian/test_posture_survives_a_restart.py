"""A restart does not loosen Guardian's posture, and a classifier never
settles an escalation that must reach a person (found writing guardian's
CONTRACT.md, 2026-09-19)."""

import unittest
from types import SimpleNamespace

from simorgh.contracts.envelope import Event
from simorgh.guardian.api import DecisionContext, Proposal, ToolInfo
from simorgh.guardian.config import Config
from simorgh.guardian.pipeline import Pipeline
from simorgh.guardian.posture import Posture
from simorgh.guardian.rules import DEFAULT_PIPELINE
from simorgh.guardian.service import TRUST_STREAM, Service


class _Ledger:
    def __init__(self, events):
        self.events = events

    async def read(self, stream, **kw):
        return [e for e in self.events if e.stream == stream]


def _ev(type_, payload):
    return Event(stream=TRUST_STREAM, type=type_, ts=1.0, trace_id="", causation_id=None, payload=payload)


class APostureSurvivesARestart(unittest.IsolatedAsyncioTestCase):
    async def _restored(self, events, **cfg):
        svc = Service(config=Config(lock_ttl_s=0, **cfg))
        svc._ctx = SimpleNamespace(ledger=_Ledger(events))  # noqa: SLF001
        await svc._restore_posture()  # noqa: SLF001
        return svc._posture.level  # noqa: SLF001

    async def test_a_lock_is_still_a_lock_after_a_restart(self):
        self.assertEqual(await self._restored([_ev("tightened", {"to": "locked", "reason": "15 failures"})]), "locked")

    async def test_a_human_reset_is_remembered_too(self):
        events = [_ev("tightened", {"to": "locked", "reason": "x"}), _ev("reset_to_baseline", {"by": "human"})]
        self.assertEqual(await self._restored(events), "guarded")

    async def test_no_history_is_the_baseline(self):
        self.assertEqual(await self._restored([]), "guarded")


class AClassifierNeverSettlesAPersonOnlyEscalation(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_allow_does_not_approve_an_unlock(self):
        async def always_allow(_proposal):
            return "ALLOW"

        proposal = Proposal("a", "home_call", {"service": "lock.unlock", "target": "lock.front"}, {}, "reversible", "t", "t")
        ctx = DecisionContext(now=0.0, system_state="running", posture=Posture(level="guarded", baseline="guarded"),
                              config=Config(irreversible_requires_human=False, classifier_enabled=True),
                              tool=ToolInfo("home_call", False, "reversible"), classify=always_allow)
        verdict = await Pipeline(DEFAULT_PIPELINE).decide(proposal, ctx)
        self.assertEqual(verdict.kind, "needs_human")
