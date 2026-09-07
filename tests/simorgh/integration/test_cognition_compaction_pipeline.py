"""Phase 4 acceptance for roadmap item 4.2 ("Context compaction layers
3-5 (cognition): reference substitution, read-time collapse, model
summarization as last resort; per-call budget accounting;
persistent-instruction protection") -- exercised over a REAL Kernel, a
real Cognition `Service`, and a real (memory-backend) Bus/Ledger, not
mocks of these classes.

This closes docs/KnowledgeBase/harness-06-gap-analysis-simorgh.md **gap
#2 by name**: "No context-compaction pipeline in any tool loop." Every
scenario below drives that gap's fix end to end through
`cognition.think`/`cognition.compact.request` exactly as another
subsystem would, rather than calling `Compactor` directly (that's
`tests/simorgh/cognition/test_compaction.py`'s job).

Only Cognition's *provider* is faked here (`_FakeProvider`, via the
`Service(providers=...)` constructor seam) -- no real subprocess/network
call is allowed in this suite. `simorgh/kernel/registry.py` itself is
left untouched; injection follows the exact seam its own docstring names
and `test_kernel_boot_two_toy_subsystems.py`/
`test_cognition_memory_boot.py` demonstrate:
`mock.patch("simorgh.kernel.service.build_factories", new=...)` wrapping
the real `build_factories` and adding a `cognition` entry."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest import mock

from simorgh.cognition.config import Config as CognitionConfig, ProviderConfig
from simorgh.cognition.service import Service as CognitionService
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from tests.simorgh.helpers import FakeClock


class _FakeProvider:
    name = "fake_llm"

    def __init__(self, *, text: str = "the real answer") -> None:
        self._text = text
        self.calls = 0
        self.received_messages: list[dict] | None = None

    def available(self) -> bool:
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        self.calls += 1
        self.received_messages = messages
        return ProviderResponse(text=self._text, provider=self.name, input_tokens=10, output_tokens=5, cost_usd=0.001)


def _patched_build_factories(*, cognition_config, cognition_providers):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["cognition"] = lambda: CognitionService(config=cognition_config, providers=cognition_providers)
        return factories

    return _build


class TestCognitionCompactionPipelineBoot(unittest.IsolatedAsyncioTestCase):
    """Roadmap 4.2, closing harness-06 gap #2 ("No context-compaction
    pipeline in any tool loop") over a real Kernel."""

    async def _boot(self, *, config=None, providers=None):
        self._tmp = tempfile.TemporaryDirectory()
        loaded = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(loaded, secrets=EnvSecretStore({}), clock=FakeClock())
        self._patch = mock.patch(
            "simorgh.kernel.service.build_factories",
            new=_patched_build_factories(
                cognition_config=config or CognitionConfig(
                    provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
                ),
                cognition_providers=providers if providers is not None else [_FakeProvider()],
            ),
        )
        self._patch.start()
        await self.kernel.boot()

    async def asyncTearDown(self):
        await self.kernel.shutdown()
        self._patch.stop()
        self._tmp.cleanup()

    async def test_kernel_boots_cognition_healthy(self):
        await self._boot()
        self.assertEqual(self.kernel.state.state, RUNNING)
        self.assertEqual(self.kernel._supervisor.services["cognition"].status, "ok")  # noqa: SLF001

    async def test_layer_1_and_2_still_fire_through_a_real_think_call(self):
        # A sanity check that this session's rewiring (the compactor now
        # sees the caller's *raw* messages, not the assembler's already-
        # flattened block) didn't regress the earlier layers.
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05, tool_result_max_tokens=50,
        )
        await self._boot(config=config)
        big_tool_result = {"role": "tool", "name": "search", "content": " ".join(f"w{i}" for i in range(500))}
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [big_tool_result],
            "budget": {"max_tokens": 1_000, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertIn(1, [int(n) for n in reply.payload["compaction"]["layers_applied"]])

    async def test_layer_3_reference_substitution_fires_through_a_real_think_call(self):
        # Roadmap 4.2's "reference substitution" layer: identical tool
        # results collapse to one reference instead of staying duplicated.
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05, microcompact_trigger_fraction=0.0,
        )
        await self._boot(config=config)
        dup = " ".join(f"w{i}" for i in range(50))
        messages = [
            {"role": "tool", "name": "search", "content": dup},
            {"role": "tool", "name": "search", "content": dup},
        ]
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": messages,
            "budget": {"max_tokens": 1_000_000, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertIn(3, [int(n) for n in reply.payload["compaction"]["layers_applied"]])

    async def test_layer_4_read_time_collapse_fires_through_a_real_think_call(self):
        # Roadmap 4.2's "read-time collapse" layer: older turns become
        # headlines, the newest turn is untouched -- and per S1's own
        # worked example, this fires even comfortably under budget.
        await self._boot()
        messages = [{"role": "user", "content": f"turn {i}"} for i in range(6)] + [
            {"role": "user", "content": "the newest message must stay in full"},
        ]
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": messages,
            "budget": {"max_tokens": 12_000, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertIn(4, [int(n) for n in reply.payload["compaction"]["layers_applied"]])

    async def test_layer_5_model_summarization_is_the_last_resort_and_emits_compact_events(self):
        # Roadmap 4.2's "model summarization as last resort": only when
        # 1-4 aren't enough AND the caller opts in with allow_summarize.
        # Unlike the standalone-service unit tests, a *real* Kernel boots
        # real Persona/World Model too, so the assembler's protected
        # blocks (constitution + voice + self-summary) are real text
        # (~150-170 tokens, not just the ~33-token constitution alone) --
        # the budget and filler count below are sized with headroom for
        # that, not tuned to the standalone-service numbers.
        seen: list[str] = []

        async def _on_pre(message):
            seen.append("pre")

        async def _on_done(message):
            seen.append("done")

        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=2.0,
            collapse_keep_full_segments=1, snip_keep_last_segments=1_000,
        )
        await self._boot(config=config, providers=[_FakeProvider(text="SUMMARY: consolidated work")])
        await self.kernel.bus.subscribe(topics.COGNITION_COMPACT_PRE, _on_pre)
        await self.kernel.bus.subscribe(topics.COGNITION_COMPACT_DONE, _on_done)

        older = [{"role": "user", "content": " ".join(f"w{i}" for i in range(30))} for _ in range(300)]
        messages = older + [{"role": "user", "content": "the newest turn"}]
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": messages,
            "budget": {"max_tokens": 1_200, "max_cost_usd": 0.1}, "require_real_provider": False,
            "allow_summarize": True, "session_id": "integration-s1",
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertNotIn("error", reply.payload)
        self.assertIn(5, [int(n) for n in reply.payload["compaction"]["layers_applied"]])
        self.assertIsNotNone(reply.payload["compaction"]["summary_ref"])

        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(seen, ["pre", "done"])

    async def test_per_call_budget_accounting_refuses_to_overspend_a_single_requests_own_budget(self):
        # Roadmap 4.2's "per-call budget accounting": a provider priced
        # over the request's own max_cost_usd is refused before any
        # money is spent, distinct from "no real provider available."
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
            providers={"fake_llm": ProviderConfig(price_in=1_000_000.0, price_out=1_000_000.0)},
        )
        await self._boot(config=config)
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "hi"}],
            "budget": {"max_tokens": 1_000, "max_cost_usd": 0.0000001}, "require_real_provider": True,
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertFalse(reply.payload["ok"])
        self.assertEqual(reply.payload["error"]["code"], "budget_exceeded")

    async def test_persistent_instruction_protection_survives_extreme_pressure_via_compact_request(self):
        # Roadmap 4.2's "persistent-instruction protection": a segment
        # tagged protected/system is never compacted away, even via the
        # caller-owned `cognition.compact.request` path (Orchestration's
        # own message list bypasses the assembler entirely). The wire
        # reply for `compact.request` doesn't echo the rendered text, so
        # this checks the one thing it does expose: `tokens_after` can
        # never drop below what's needed to hold the protected segment
        # verbatim, no matter how aggressive the target.
        await self._boot()
        protected_text = "PROTECTED: never drop this instruction"
        messages = [
            {"role": "system", "content": protected_text, "protected": True},
        ] + [
            {"role": "tool", "name": "search", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(5)
        ]
        request = Message.new(topics.COGNITION_COMPACT_REQUEST, source="test", payload={
            "session_id": "integration-s2", "target_tokens": 5, "messages": messages,
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertIn("layers_applied", reply.payload)
        min_tokens_for_protected_text = (len(protected_text) + 3) // 4
        self.assertGreaterEqual(reply.payload["tokens_after"], min_tokens_for_protected_text)

    async def test_persistent_instruction_protection_survives_in_what_the_provider_actually_sees(self):
        # The stronger version of the check above: via `cognition.think`,
        # a protected segment inside the caller's own message list must
        # still be present, verbatim, in the exact text the real provider
        # is called with -- not just accounted for in a token count.
        fake = _FakeProvider(text="ok")
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
            collapse_keep_full_segments=1, snip_keep_last_segments=100,
        )
        await self._boot(config=config, providers=[fake])
        protected_text = "PROTECTED: never drop this instruction"
        older = [{"role": "user", "content": " ".join(f"w{i}" for i in range(30))} for _ in range(15)]
        messages = [{"role": "system", "content": protected_text, "protected": True}] + older + [
            {"role": "user", "content": "the newest turn"},
        ]
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": messages,
            "budget": {"max_tokens": 500, "max_cost_usd": 0.1}, "require_real_provider": False,
            "allow_summarize": True, "session_id": "integration-s3",
        })
        reply = await self.kernel.bus.request(request, timeout=5.0)
        self.assertNotIn("error", reply.payload)
        self.assertIsNotNone(fake.received_messages)
        # Milestone 120: the provider now sees separate `role: "system"`
        # (assembler-level protected blocks, e.g. self-model identity) and
        # `role: "user"` (the compacted conversation) messages instead of
        # one flattened blob -- but this caller-tagged protected *message*
        # (distinct from the assembler's own protected blocks) is preserved
        # by the compactor within the conversation text, so check across
        # every message the provider actually received rather than
        # assuming which role it landed on.
        sent_text = "\n\n".join(m["content"] for m in fake.received_messages)
        self.assertIn(protected_text, sent_text)
        self.assertIn("the newest turn", sent_text)


if __name__ == "__main__":
    unittest.main()
