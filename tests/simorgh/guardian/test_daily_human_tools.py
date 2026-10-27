"""Stage 18 item 12: Guardian's one rule for Claude Code, and the list it
hands Execution.

- `daily_human_tools` (`claude_code_task`): the first call of each local
  day escalates to a person in every posture; after a "yes" the ordinary
  rules decide the rest of that day; the "yes" survives a restart; the
  next day asks again; locked denies.
- `guardian:protected`: written at every start with the configured
  `protected_subjects`, which is what `execution/worktree.py` refuses at
  landing.

Over a real Guardian Service on the memory bus.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.guardian.api import Proposal
from simorgh.guardian.config import DEFAULT_PROTECTED_SUBJECTS, Config
from simorgh.guardian.posture import Posture
from simorgh.guardian.rules import HumanOnlyRule
from simorgh.guardian.service import DAILY_STREAM, PROTECTED_STREAM, Service
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


def _proposal(tool: str = "claude_code_task") -> Proposal:
    return Proposal("a1", tool, {"feature": "x"}, {}, "irreversible", "t1", "patch")


def _ctx(level: str = "guarded", approved=None, mode: str = "guarded"):
    return SimpleNamespace(posture=Posture(level=level, baseline="guarded"), config=Config(mode=mode),
                           approved_today=approved)


class TheRule(unittest.IsolatedAsyncioTestCase):
    async def test_the_first_run_of_the_day_asks_a_person(self):
        decision = await HumanOnlyRule().evaluate(_proposal(), _ctx())
        self.assertEqual(decision.kind, "escalate")
        self.assertIn("first claude_code_task of the day", decision.reasons[0])

    async def test_nobody_able_to_say_is_not_yet(self):
        decision = await HumanOnlyRule().evaluate(_proposal(), SimpleNamespace(
            posture=Posture(level="guarded", baseline="guarded"), config=Config()))
        self.assertEqual(decision.kind, "escalate")

    async def test_after_a_yes_today_the_ordinary_rules_decide(self):
        decision = await HumanOnlyRule().evaluate(_proposal(), _ctx(approved=lambda tool: True))
        self.assertEqual(decision.kind, "abstain")

    async def test_in_every_posture_and_locked_denies(self):
        self.assertEqual((await HumanOnlyRule().evaluate(_proposal(), _ctx(level="trusted"))).kind, "escalate")
        self.assertEqual((await HumanOnlyRule().evaluate(_proposal(), _ctx(level="locked"))).kind, "deny")

    async def test_other_tools_are_untouched(self):
        self.assertEqual((await HumanOnlyRule().evaluate(_proposal("run_tests"), _ctx())).kind, "abstain")

    def test_it_is_a_person_only_layer_that_never_stands(self):
        from simorgh.guardian.pipeline import _PERSON_ONLY_LAYERS
        from simorgh.guardian.service import NEVER_STANDING

        self.assertIn("human_only", NEVER_STANDING, "'always' must not turn a daily ask into never asking")
        self.assertIn("human_only", _PERSON_ONLY_LAYERS, "a classifier must not settle it")

    def test_the_default_lists_claude_code(self):
        self.assertIn("claude_code_task", Config().daily_human_tools)
        self.assertEqual(Config.from_mapping({"daily_human_tools": []}).daily_human_tools, ())


class OverTheBus(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.proposer = make_client(self.backend, source="orchestration", ledger=self.ledger, clock=self.clock)
        self.listener = make_client(self.backend, source="execution", ledger=self.ledger, clock=self.clock)
        self.person = make_client(self.backend, source="interface", ledger=self.ledger, clock=self.clock)
        for client in (self.proposer, self.listener, self.person):
            await client.start()
        self.outcomes: dict[str, asyncio.Future] = {}
        for topic in (topics.ACTION_APPROVED, topics.ACTION_DENIED, topics.ACTION_NEEDS_HUMAN):
            await self.listener.subscribe(topic, self._on_outcome)
        self.guardian = await self._guardian()

    async def asyncTearDown(self):
        await self.guardian.stop()
        self._tmp.cleanup()

    async def _guardian(self) -> Service:
        bus = make_client(self.backend, source="guardian", ledger=self.ledger, clock=self.clock)
        await bus.start()
        service = Service(config=Config(irreversible_requires_human=False))
        await service.start(Context(
            name="guardian", instance_id="", run_id="test", mode="single", bus=bus, ledger=self.ledger,
            config={}, secrets={"__hmac__": "00" * 32}, clock=self.clock, logger=_Logger(),
            data_dir=Path(self._tmp.name)))
        return service

    async def _on_outcome(self, message: Message) -> None:
        fut = self.outcomes.get((message.payload or {}).get("action_id"))
        if fut is not None and not fut.done():
            fut.set_result(message.type)

    async def _propose(self, action_id: str) -> str:
        self.outcomes[action_id] = asyncio.get_running_loop().create_future()
        await self.proposer.publish(Message.new(topics.ACTION_PROPOSED, source="orchestration", payload={
            "action_id": action_id, "tool": "claude_code_task", "args": {"feature": "a test"},
            "scope": {"paths": [], "network": True}, "reversibility": "irreversible",
            "rationale": "test", "proposed_by": "orchestration", "requester": None, "requester_channel": "cli"}))
        return await asyncio.wait_for(self.outcomes[action_id], timeout=5.0)

    async def _answer(self, action_id: str, answer: str) -> str:
        self.outcomes[action_id] = asyncio.get_running_loop().create_future()
        await self.person.publish(Message.new(topics.UI_PROMPT_ANSWERED, source="interface",
                                              payload={"prompt_id": action_id, "answer": answer}))
        return await asyncio.wait_for(self.outcomes[action_id], timeout=5.0)

    async def test_once_a_day_and_the_yes_survives_a_restart(self):
        self.assertEqual(await self._propose("cc-1"), topics.ACTION_NEEDS_HUMAN)
        self.assertEqual(await self._answer("cc-1", "yes"), topics.ACTION_APPROVED)
        (event,) = await self.ledger.read(DAILY_STREAM)
        self.assertEqual(event.payload["tool"], "claude_code_task")

        self.assertEqual(await self._propose("cc-2"), topics.ACTION_APPROVED, "the second run that day")

        await self.guardian.stop()
        self.guardian = await self._guardian()
        self.assertEqual(await self._propose("cc-3"), topics.ACTION_APPROVED, "a restart does not ask again")

        self.clock.advance(86_400.0)
        self.assertEqual(await self._propose("cc-4"), topics.ACTION_NEEDS_HUMAN, "the next day asks again")

    async def test_a_no_is_not_remembered_as_a_yes(self):
        self.assertEqual(await self._propose("cc-1"), topics.ACTION_NEEDS_HUMAN)
        self.assertEqual(await self._answer("cc-1", "no"), topics.ACTION_DENIED)
        self.assertEqual(await self.ledger.read(DAILY_STREAM), [])
        self.assertEqual(await self._propose("cc-2"), topics.ACTION_NEEDS_HUMAN)

    async def test_the_protected_subjects_are_written_at_start(self):
        events = await self.ledger.read(PROTECTED_STREAM)
        self.assertEqual(events[-1].type, "subjects")
        self.assertEqual(tuple(events[-1].payload["protected_subjects"]), DEFAULT_PROTECTED_SUBJECTS)


if __name__ == "__main__":
    unittest.main()
