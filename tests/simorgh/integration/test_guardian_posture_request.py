"""`guardian.posture.request` -> `.reply` over a REAL Kernel with the real
Guardian (post-cutover review, 2026-09-06 -- `docs/blueprint/
07-post-cutover-review.md` §3.6): the pair existed in the contracts
catalog and Interface's `budget` command sent the request, but nothing
ever answered, so the command timed out every time. Boot pattern copied
from `test_guardian_execution_action_path.py`."""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.guardian.config import Config as GuardianConfig
from simorgh.guardian.service import Service as GuardianService
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING


def _patched_build_factories():
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["guardian"] = lambda: GuardianService(config=GuardianConfig(mode="guarded"))
        return factories

    return _build


class TestGuardianPostureRequest(unittest.IsolatedAsyncioTestCase):
    async def test_posture_request_gets_a_real_reply_with_the_contracts_mode_field(self):
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

        reply = await kernel.bus.request(
            Message.new(topics.GUARDIAN_POSTURE_REQUEST, source="test", payload={}), timeout=3.0,
        )
        self.assertEqual(reply.type, topics.GUARDIAN_POSTURE_REPLY)
        self.assertEqual(reply.payload["mode"], "guarded")
        self.assertEqual(reply.payload["tightened_by"], [])
        self.assertIn("trust_score", reply.payload)


if __name__ == "__main__":
    unittest.main()
