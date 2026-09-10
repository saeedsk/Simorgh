"""Provider order, through a real Kernel boot: the cloud model is the
primary brain and everything else is failover behind it (project policy,
`docs/plans/voice-design.md`). Two things have to hold at once, and they
pull against each other:

- the configured primary is what answers while it is healthy -- a
  fallback must never quietly become the thing doing the thinking;
- a *transient* primary failure must not pin the system to the fallback
  for the rest of the run. The Router's cooldown is deliberately short
  for exactly this reason, and nothing tested that it ever expires
  through a real boot rather than a unit-level clock nudge.

Only the providers are fake (the `Service(providers=...)` seam) -- no
network call, no money. The Kernel, Bus, Ledger and Cognition `Service`
are the real ones.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from simorgh.cognition.api import ProviderUnavailable
from simorgh.cognition.config import Config as CognitionConfig
from simorgh.cognition.service import Service as CognitionService
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from tests.simorgh.helpers import FakeClock


class _Provider:
    """A provider whose health this test controls, call by call."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.calls = 0
        self.fail_next = False

    def available(self) -> bool:
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise ProviderUnavailable(f"{self.name}: transient 502")
        return ProviderResponse(text=f"answered by {self.name}", provider=self.name, cost_usd=0.0)


def _patched_build_factories(*, providers):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(
            bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl,
            guardian_config=guardian_config,
        )
        factories["cognition"] = lambda: CognitionService(
            config=CognitionConfig(
                provider_order=("together", "gemini", "floor"), assembly_request_timeout=0.05,
            ),
            providers=providers,
        )
        return factories

    return _build


class CognitionFailoverOrderingTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.primary = _Provider("together")   # the cloud model: the primary brain
        self.fallback = _Provider("gemini")    # failover only
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}), clock=self.clock)
        self._patch = mock.patch(
            "simorgh.kernel.service.build_factories",
            new=_patched_build_factories(providers=[self.primary, self.fallback]),
        )
        self._patch.start()
        await self.kernel.boot()

    async def asyncTearDown(self):
        await self.kernel.shutdown()
        self._patch.stop()
        self._tmp.cleanup()

    async def _think(self) -> Message:
        return await self.kernel.bus.request(Message.new(
            topics.COGNITION_THINK, source="test", payload={
                "purpose": "chat", "messages": [{"role": "user", "content": "hello"}],
                "budget": {"max_tokens": 100, "max_cost_usd": 0.1},
                "require_real_provider": False,
            },
        ), timeout=10.0)

    async def test_the_primary_answers_and_the_fallback_is_never_dialled(self):
        reply = await self._think()
        self.assertEqual(reply.payload["provider"], "together")
        self.assertFalse(reply.payload["floor"])
        self.assertEqual(self.fallback.calls, 0, "a fallback must not be doing the thinking")

    async def test_a_transient_primary_failure_falls_over_and_then_comes_back(self):
        self.primary.fail_next = True
        first = await self._think()
        self.assertEqual(first.payload["provider"], "gemini", "one primary failure must fail over")

        # How long the cooldown holds is asserted at unit level
        # (`TheCooldownIsStampedWhenTheFailureHappensTestCase`), not here:
        # under a real boot every other subsystem shares this `FakeClock`
        # and each `await clock.sleep(...)` drags it forward by its own
        # interval, so wall-clock windows are not this test's to control.
        # What a real boot *can* prove is the part that matters to the
        # policy: the primary comes back.
        self.clock.advance(60.0)
        after = await self._think()
        self.assertEqual(after.payload["provider"], "together", "the primary was never given another chance")


if __name__ == "__main__":
    unittest.main()
