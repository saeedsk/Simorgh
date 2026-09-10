"""One proposal, one decision.

The gate had no idempotency, and the bus is at-least-once by design. So
a redelivered `action.proposed` was decided a second time and minted a
second approval token -- which then failed Execution's replay guard, so
a real, successful action was ALSO reported as `action.denied` with
reason "signature replayed", and Execution marked itself degraded over
an ordinary redelivery. Orchestration waits on result-or-denial and
takes whichever lands first, so the model could be told that the action
it had just run was refused for a token-integrity failure.

Observed by an observer over a real Kernel, 2026-09-10, in the ledger:
`action:dup-1` carried `[received, decided, verified(ok), received,
decided, verified(mismatch)]`.

Nothing wrong ever executed -- Execution pins the arguments from the
FIRST proposal and fails closed -- but a tamper alarm that fires on
ordinary redelivery is worse than no alarm at all.
"""

import asyncio
import tempfile
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

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _patched_build_factories():
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl,
                         guardian_config=guardian_config)
        factories["guardian"] = lambda: GuardianService(config=GuardianConfig(mode="guarded"))
        factories["execution"] = lambda: ExecutionService(config=ExecutionConfig(repo_root=_REPO_ROOT))
        return factories

    return _build


def _proposal(action_id: str, *, args: dict) -> Message:
    return Message.new(
        topics.ACTION_PROPOSED, source="test",
        payload={"action_id": action_id, "tool": "read_file", "args": args,
                 "scope": {"network": False}, "reversibility": "read_only",
                 "rationale": "integration test", "proposed_by": "test"},
    )


class GuardianDecidesOncePerActionTestCase(unittest.IsolatedAsyncioTestCase):
    async def _boot(self) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp.name}}, None),
                        secrets=EnvSecretStore({}))
        patcher = mock.patch("simorgh.kernel.service.build_factories",
                             new=_patched_build_factories())
        patcher.start()
        self.addCleanup(patcher.stop)
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        self.denials: list[Message] = []
        self.results: list[Message] = []
        await kernel.bus.subscribe(topics.ACTION_DENIED, self._on_denied)
        await kernel.bus.subscribe(topics.ACTION_RESULT, self._on_result, group="collector-result")
        return kernel

    async def _on_denied(self, message: Message) -> None:
        self.denials.append(message)

    async def _on_result(self, message: Message) -> None:
        self.results.append(message)

    async def _settle(self, n: int = 200) -> None:
        for _ in range(n):
            await asyncio.sleep(0.01)
            if self.results or self.denials:
                # give any second, spurious answer time to arrive too
                for _ in range(20):
                    await asyncio.sleep(0.01)
                return

    async def test_a_redelivered_proposal_is_not_answered_twice(self):
        kernel = await self._boot()
        args = {"path": "README.md"}
        await kernel.bus.publish(_proposal("dup-same", args=args))
        await kernel.bus.publish(_proposal("dup-same", args=args))
        await self._settle()

        replayed = [m for m in self.denials
                    if m.payload.get("action_id") == "dup-same"
                    and "replay" in " ".join(m.payload.get("reasons") or []).lower()]
        self.assertEqual(replayed, [], "a redelivery must not read as a token replay")

    async def test_the_same_id_carrying_a_different_action_is_denied_at_the_gate(self):
        """Not left to fail downstream as a signature mismatch, which
        reads as tampering rather than as a reused id."""
        kernel = await self._boot()
        await kernel.bus.publish(_proposal("dup-different", args={"path": "README.md"}))
        await kernel.bus.publish(_proposal("dup-different", args={"path": "CLAUDE.md"}))
        await self._settle()

        denials = [m for m in self.denials if m.payload.get("action_id") == "dup-different"]
        self.assertTrue(denials, "a reused id must be refused")
        self.assertEqual(denials[0].payload.get("layer"), "policy")
        self.assertIn("already been decided", " ".join(denials[0].payload.get("reasons") or []))


if __name__ == "__main__":
    unittest.main()
