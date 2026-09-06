"""Phase 1A acceptance (docs/blueprint/subsystems/04-cognition.md /
05-memory.md section 9): a real Kernel boots real Cognition and real
Memory `Service` instances -- not toys, not mocks of these classes --
over the real composition root. `simorgh/kernel/registry.py` itself is
left untouched (it is a shared file other Phase 1 tracks are also
landing work in); the injection follows the exact seam the registry's
own docstring names and `test_kernel_boot_two_toy_subsystems.py`
demonstrates: `mock.patch("simorgh.kernel.service.build_factories", ...)`
wrapping the real `build_factories` and adding entries for the layer(s)
not yet wired into the shared registry.

Only Cognition's *provider* is fake here (`_FakeProvider`, via the
`Service(providers=...)` constructor seam) -- no real subprocess/network
call is allowed in this suite. Memory's Ledger/Bus are the real Phase 0
clients, exactly as the Kernel builds them."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest import mock

from simorgh.cognition.config import Config as CognitionConfig
from simorgh.cognition.service import Service as CognitionService
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from simorgh.memory.service import Service as MemoryService
from tests.simorgh.helpers import FakeClock


class _FakeProvider:
    name = "fake_llm"

    def available(self) -> bool:
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        return ProviderResponse(text="READ: src/foo.py\nbecause it's relevant", provider=self.name, cost_usd=0.0)


def _patched_build_factories(*, cognition_providers):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["cognition"] = lambda: CognitionService(
            config=CognitionConfig(provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05),
            providers=cognition_providers,
        )
        factories["memory"] = lambda: MemoryService()
        return factories

    return _build


class TestCognitionMemoryBoot(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, *, cognition_providers):
        self._tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
        self._patch = mock.patch(
            "simorgh.kernel.service.build_factories", new=_patched_build_factories(cognition_providers=cognition_providers),
        )
        self._patch.start()
        await self.kernel.boot()

    async def asyncTearDown(self):
        await self.kernel.shutdown()
        self._patch.stop()
        self._tmp.cleanup()

    async def test_kernel_boots_both_and_they_are_healthy(self):
        await self._boot(cognition_providers=[_FakeProvider()])
        self.assertEqual(self.kernel.state.state, RUNNING)
        self.assertEqual(self.kernel._supervisor.services["cognition"].status, "ok")  # noqa: SLF001
        self.assertEqual(self.kernel._supervisor.services["memory"].status, "ok")  # noqa: SLF001

    async def test_cognition_think_with_a_fake_provider_returns_correctly_parsed_tool_calls(self):
        await self._boot(cognition_providers=[_FakeProvider()])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "find the bug"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
            "expected": "tool_calls", "tools": ["READ", "DRAFT"],
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertFalse(reply.payload["floor"])
        self.assertEqual(reply.payload["tool_calls"], [{"tool": "read", "args": {"argument": "src/foo.py"}}])

    async def test_cognition_think_with_no_provider_returns_an_honest_floor_reply(self):
        await self._boot(cognition_providers=[])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "hi"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertTrue(reply.payload["floor"])
        self.assertEqual(reply.payload["provider"], "floor")

    async def test_memory_store_then_retrieve_round_trip_finds_it_with_a_sane_score(self):
        await self._boot(cognition_providers=[])
        done: asyncio.Future = asyncio.get_running_loop().create_future()

        async def _on_stored(message: Message) -> None:
            if not done.done():
                done.set_result(message)

        sub = await self.kernel.bus.subscribe(topics.MEMORY_STORED, _on_stored)
        try:
            await self.kernel.bus.publish(Message.new(topics.MEMORY_STORE, source="test", payload={
                "kind": "semantic", "content": "simorgh boots cognition and memory together", "tags": [], "source_ref": "",
            }))
            await asyncio.wait_for(done, timeout=5.0)
        finally:
            await sub.unsubscribe()

        reply = await self.kernel.bus.request(Message.new(topics.MEMORY_RETRIEVE, source="test", payload={
            "query": "boots cognition and memory", "kinds": ["semantic"], "k": 5,
        }), timeout=5.0)
        self.assertEqual(len(reply.payload["items"]), 1)
        self.assertGreater(reply.payload["items"][0]["score"], 0.0)
        self.assertLessEqual(reply.payload["items"][0]["score"], 1.0 + 1e-9)


if __name__ == "__main__":
    unittest.main()
