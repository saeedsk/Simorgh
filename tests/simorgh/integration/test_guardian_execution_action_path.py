"""Phase 1B acceptance: the same four properties `simorgh.kernel.selfcheck`
proves with inline stubs (docs/blueprint/subsystems/03-kernel.md section
5.4), reproduced here with the REAL `simorgh.guardian.Service` and
`simorgh.execution.Service`, booted through the real Kernel composition
root (`registry.build_factories` -> `ContextFactory` -> `Supervisor`), so
this is a proof about the actual subsystems, not the wire alone. Adds a
fifth property the stubs couldn't: a real tool (`read_file`) actually runs
and returns real content.

`action.approved` is reserved for subscription to `execution` alone
(03-contracts-and-messaging.md section 3), so this test's own collector
-- an ordinary, non-reserved client -- only ever observes `action.denied`
and `action.result`; a successful `action.result` is sufficient proof an
approval happened (Guardian is the only publisher of a *valid* one).
"""

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.service import Service as ExecutionService
from simorgh.guardian.config import Config as GuardianConfig
from simorgh.guardian.service import Service as GuardianService
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _patched_build_factories():
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl, guardian_config=guardian_config)
        factories["guardian"] = lambda: GuardianService(config=GuardianConfig(mode="guarded"))
        factories["execution"] = lambda: ExecutionService(config=ExecutionConfig(repo_root=_REPO_ROOT))
        return factories

    return _build


class _Collector:
    """Observes the topics an ordinary (non-reserved) client is allowed
    to subscribe to on the action path, plus `action.needs_human` and
    `ui.prompt` (both broadcast, no reservation) for the real-approval
    tests below."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self.events: list[Message] = []

    async def start(self) -> None:
        await self.bus.subscribe(topics.ACTION_DENIED, self._on)
        await self.bus.subscribe(topics.ACTION_RESULT, self._on, group="collector-result")
        await self.bus.subscribe(topics.ACTION_NEEDS_HUMAN, self._on)
        await self.bus.subscribe(topics.UI_PROMPT, self._on)

    async def _on(self, message: Message) -> None:
        self.events.append(message)


async def _wait_for(events: list, action_id: str, type_: str, *, attempts: int = 300):
    for _ in range(attempts):
        for m in events:
            # ui.prompt keys its payload by `prompt_id`, not `action_id`
            # (it's a generic question/answer contract Guardian reuses,
            # not action-specific) -- `prompt_id == action_id` by
            # `_on_proposed`'s own construction, so either field name
            # correlates a `ui.prompt` back to the same proposal.
            id_ = m.payload.get("action_id") or m.payload.get("prompt_id")
            if id_ == action_id and m.type == type_:
                return m
        await asyncio.sleep(0.01)
    return None


def _proposal(action_id: str, *, tool: str, args: dict, reversibility: str = "read_only") -> Message:
    return Message.new(
        topics.ACTION_PROPOSED, source="test",
        payload={"action_id": action_id, "tool": tool, "args": args,
                 "scope": {"network": False}, "reversibility": reversibility,
                 "rationale": "integration test", "proposed_by": "test"},
    )


class TestGuardianExecutionActionPath(unittest.IsolatedAsyncioTestCase):
    async def _boot(self) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        # A real wall clock, not FakeClock: the Kernel's Scheduler runs
        # `while True: await clock.sleep(1.0)` tick loops that, under a
        # FakeClock (whose `sleep` just bumps a counter and yields once),
        # race arbitrarily far ahead of real time -- enough to blow past
        # the 120s approval TTL within milliseconds of wall-clock waiting.
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patcher = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories())
        patcher.start()
        await kernel.boot()
        self.addCleanup(patcher.stop)
        self.addCleanup(tmp.cleanup)
        self.addAsyncCleanup(kernel.shutdown)
        self.assertEqual(kernel.state.state, RUNNING)
        return kernel

    async def test_legitimate_proposal_is_approved_and_a_real_tool_runs(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(_proposal(
            "a1", tool="read_file", args={"path": "docs/blueprint/subsystems/09-guardian.md"},
        ))
        result = await _wait_for(collector.events, "a1", topics.ACTION_RESULT)

        self.assertIsNotNone(result, "no action.result arrived -- approval or execution never happened")
        self.assertTrue(result.payload["ok"], result.payload)
        self.assertIn("Simorgh", result.payload["stdout_preview"])

    async def test_forged_approval_is_rejected_before_any_tool_runs(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        forged = Message.new(
            topics.ACTION_APPROVED, source="guardian",  # only guardian/kernel may publish this topic at all
            payload={"action_id": "forged-1", "tool": "read_file", "args_sha256": "0" * 64,
                     "expires_at": time.time() + 60,
                     "approval_token": "f" * 64, "mode_at_approval": "guarded"},
        )
        await kernel.bus.publish(forged)
        result = await _wait_for(collector.events, "forged-1", topics.ACTION_RESULT, attempts=30)
        denied = await _wait_for(collector.events, "forged-1", topics.ACTION_DENIED)

        self.assertIsNone(result, "a forged approval must never produce a successful action.result")
        self.assertIsNotNone(denied)
        self.assertEqual(denied.payload["layer"], "token")

    async def test_paused_system_denies_a_new_proposal(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(Message.new(topics.SYSTEM_PAUSE, source="kernel",
                                              payload={"reason": "test", "requested_by": "test"}, priority=9))
        await asyncio.sleep(0.05)

        await kernel.bus.publish(_proposal(
            "paused-1", tool="read_file", args={"path": "docs/blueprint/subsystems/09-guardian.md"},
        ))
        denied = await _wait_for(collector.events, "paused-1", topics.ACTION_DENIED)

        self.assertIsNotNone(denied)
        self.assertEqual(denied.payload["layer"], "paused")

    async def test_protected_subject_is_denied_regardless_of_mode(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(_proposal(
            "protected-1", tool="apply_source_patch",
            args={"subject": "docs/SOUL.md", "code": "tampered"}, reversibility="reversible",
        ))
        denied = await _wait_for(collector.events, "protected-1", topics.ACTION_DENIED)

        self.assertIsNotNone(denied)
        # The wire schema's DENY_LAYER enum has no dedicated "protected"
        # value -- the protected-subject rule collapses to the general
        # "policy" bucket on the wire (see guardian/service.py's
        # _WIRE_DENY_LAYER); the specific rule that fired is in reasons.
        self.assertEqual(denied.payload["layer"], "policy")
        self.assertIn("protected", denied.payload["reasons"][0])


class TestNeedsHumanIsActuallyAnswerable(unittest.IsolatedAsyncioTestCase):
    """Live-caught (the creator, real use): `action.needs_human` was
    published and then never consumed by anything -- there was no way
    for a real "yes" to ever reach Guardian and let the action through.
    Fixed by also publishing `ui.prompt` (`prompt_id = action_id`) and
    having Guardian answer `ui.prompt_answered` for it directly, reusing
    the pre-existing question/answer contract instead of a new one."""

    async def _boot(self) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patcher = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories())
        patcher.start()
        await kernel.boot()
        self.addCleanup(patcher.stop)
        self.addCleanup(tmp.cleanup)
        self.addAsyncCleanup(kernel.shutdown)
        self.assertEqual(kernel.state.state, RUNNING)
        return kernel

    async def test_needs_human_also_publishes_a_real_answerable_prompt(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(_proposal(
            "human-1", tool="propose_mcp_server",
            args={"proposal": "name: ddg_search\ncommand: npx\nreason: test"}, reversibility="irreversible",
        ))
        prompt = await _wait_for(collector.events, "human-1", topics.UI_PROMPT)
        self.assertIsNotNone(prompt, "action.needs_human never produced an answerable ui.prompt")
        self.assertEqual(prompt.payload["prompt_id"], "human-1")
        self.assertEqual(prompt.payload["options"], ["yes", "no"])

    async def test_a_real_yes_answer_approves_it_and_the_tool_actually_runs(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(_proposal(
            "human-2", tool="propose_mcp_server",
            args={"proposal": "name: ddg_search\ncommand: npx\nreason: test"}, reversibility="irreversible",
        ))
        self.assertIsNotNone(await _wait_for(collector.events, "human-2", topics.UI_PROMPT))

        await kernel.bus.publish(Message.new(
            topics.UI_PROMPT_ANSWERED, source="test", payload={"prompt_id": "human-2", "answer": "yes"},
        ))
        result = await _wait_for(collector.events, "human-2", topics.ACTION_RESULT)
        self.assertIsNotNone(result, "no action.result after a real 'yes' answer")
        self.assertTrue(result.payload["ok"], result.payload)

    async def test_a_real_no_answer_denies_it(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(_proposal(
            "human-3", tool="propose_mcp_server",
            args={"proposal": "name: ddg_search\ncommand: npx\nreason: test"}, reversibility="irreversible",
        ))
        self.assertIsNotNone(await _wait_for(collector.events, "human-3", topics.UI_PROMPT))

        await kernel.bus.publish(Message.new(
            topics.UI_PROMPT_ANSWERED, source="test", payload={"prompt_id": "human-3", "answer": "no"},
        ))
        denied = await _wait_for(collector.events, "human-3", topics.ACTION_DENIED)
        self.assertIsNotNone(denied)
        self.assertIn("human declined", denied.payload["reasons"])

    async def test_answering_twice_only_resolves_once(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(_proposal(
            "human-4", tool="propose_mcp_server",
            args={"proposal": "name: ddg_search\ncommand: npx\nreason: test"}, reversibility="irreversible",
        ))
        self.assertIsNotNone(await _wait_for(collector.events, "human-4", topics.UI_PROMPT))

        for answer in ("yes", "no"):  # the second answer, whatever it is, must be a no-op
            await kernel.bus.publish(Message.new(
                topics.UI_PROMPT_ANSWERED, source="test", payload={"prompt_id": "human-4", "answer": answer},
            ))
        await asyncio.sleep(0.1)
        results = [m for m in collector.events if m.payload.get("action_id") == "human-4" and m.type == topics.ACTION_RESULT]
        denials = [m for m in collector.events if m.payload.get("action_id") == "human-4" and m.type == topics.ACTION_DENIED]
        self.assertEqual(len(results) + len(denials), 1, "a second answer must never re-resolve an already-answered action")

    async def test_an_unrelated_prompt_id_is_ignored_not_a_crash(self):
        kernel = await self._boot()
        collector = _Collector(kernel.bus)
        await collector.start()

        await kernel.bus.publish(Message.new(
            topics.UI_PROMPT_ANSWERED, source="test", payload={"prompt_id": "no-such-action", "answer": "yes"},
        ))
        await asyncio.sleep(0.1)  # must not raise, and must not fabricate any action.* event
        self.assertEqual([m for m in collector.events if m.payload.get("action_id") == "no-such-action"], [])


if __name__ == "__main__":
    unittest.main()
