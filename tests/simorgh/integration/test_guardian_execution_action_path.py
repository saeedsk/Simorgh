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

    def _build(*, bus_client, ledger_client, run_repl=False):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["guardian"] = lambda: GuardianService(config=GuardianConfig(mode="guarded"))
        factories["execution"] = lambda: ExecutionService(config=ExecutionConfig(repo_root=_REPO_ROOT))
        return factories

    return _build


class _Collector:
    """Observes the two topics an ordinary (non-reserved) client is
    allowed to subscribe to on the action path."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self.events: list[Message] = []

    async def start(self) -> None:
        await self.bus.subscribe(topics.ACTION_DENIED, self._on)
        await self.bus.subscribe(topics.ACTION_RESULT, self._on, group="collector-result")

    async def _on(self, message: Message) -> None:
        self.events.append(message)


async def _wait_for(events: list, action_id: str, type_: str, *, attempts: int = 300):
    for _ in range(attempts):
        for m in events:
            if m.payload.get("action_id") == action_id and m.type == type_:
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


if __name__ == "__main__":
    unittest.main()
