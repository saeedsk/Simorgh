"""Stage 4 item 4: the system prefix a provider sees is byte-identical from
one step to the next, so a caching provider can reuse it; per-step words
(the budget hints) ride at the head of the latest user turn."""

import dataclasses

from simorgh.cognition.config import Config as CognitionConfig, ProviderConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse

from .test_service import CognitionServiceTestCase


class _Recording:
    def __init__(self):
        self.name = "p"
        self.seen = []

    def available(self):
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        self.seen.append(messages)
        return ProviderResponse(text="ok", provider=self.name, cost_usd=0.0, cached_input_tokens=0)


class TheSystemPrefixIsStable(CognitionServiceTestCase):
    async def test_two_steps_share_the_system_prefix(self):
        provider = _Recording()
        base = CognitionConfig()
        config = dataclasses.replace(base, provider_order=("p", "floor"), assembly_request_timeout=0.05, providers={
            **base.providers, "p": ProviderConfig(max_calls=10, window_seconds=3600.0)})
        await self._make(providers=[provider], config=config)

        async def think(messages, **extra):
            await self.bus.request(Message.new(topics.COGNITION_THINK, source="test", payload={
                "purpose": "draft", "messages": messages, "task_rules": "Your task: fix the bug.",
                "budget": {"max_tokens": 500, "max_cost_usd": 0.1}, "require_real_provider": False, **extra,
            }), timeout=5.0)

        await think([{"role": "user", "content": "fix it"}], steps_left=9)
        await think([{"role": "user", "content": "fix it"}, {"role": "assistant", "content": "READ_FILE: a.py"},
                     {"role": "user", "content": "Result of read_file:\nx = 1"}], last_step=True)
        first, second = provider.seen
        system = lambda ms: [m["content"] for m in ms if m["role"] == "system"]  # noqa: E731
        self.assertEqual(system(first), system(second))
        self.assertNotIn("last step", "".join(system(second)))
        self.assertIn("This is your last step", second[-1]["content"])
