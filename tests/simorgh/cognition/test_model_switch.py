"""`/model` (2026-10-27): the creator typed it and the model answered in
prose ("say which one and I'll switch") with nothing behind it. Now the
providers are listed and one moves to the front, live and into
simorgh.toml; `opus`/`sonnet`/`haiku` run the Claude Code CLI with that
model."""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from simorgh.bus.factory import make_client
from simorgh.cognition.config import Config as CognitionConfig
from simorgh.cognition.providers.claude_code import ClaudeCodeProvider
from simorgh.cognition.service import Service
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from tests.simorgh.cognition import test_service as _ts
from tests.simorgh.cognition.test_service import _FakeProvider


class _Claude(_FakeProvider):
    def __init__(self):
        super().__init__("claude_code_cli")
        self.model = ClaudeCodeProvider.UNNAMED

    def set_model(self, model):
        self.model = model


class ModelSwitch(unittest.IsolatedAsyncioTestCase):
    # The service harness without its tests (subclassing would run them twice).
    _make = _ts.CognitionServiceTestCase._make
    asyncTearDown = _ts.CognitionServiceTestCase.asyncTearDown

    async def _boot(self):
        self.toml = Path(tempfile.mkdtemp()) / "simorgh.toml"
        self.toml.write_text('[voice]\ntts = "elevenlabs"\n')
        self.glm, self.claude = _FakeProvider("together"), _Claude()
        self.glm.model = "zai-org/GLM-5.3-Flash"
        config = CognitionConfig(provider_order=("together", "claude_code_cli", "floor"),
                                 assembly_request_timeout=0.05)
        await self._make(providers=[self.glm, self.claude], config=config)
        await self.service.stop()
        self.service = Service(config=config, providers=[self.glm, self.claude], config_path=self.toml)
        await self.service.start(self.ctx)
        self.interface = make_client(self.bus._backend, source="interface", ledger=self.ledger, clock=self.clock)  # noqa: SLF001
        await self.interface.start()

    async def _ask(self, **payload):
        reply = await self.interface.request(Message.new(topics.COGNITION_MODEL_REQUEST, source="interface",
                                                         payload=payload), timeout=5.0)
        return reply.payload

    async def _think(self):
        reply = await self.bus.request(Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "hi"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
        }), timeout=5.0)
        return reply.payload["provider"]

    async def test_a_bare_request_lists_and_changes_nothing(self):
        await self._boot()
        listed = await self._ask()
        self.assertEqual(listed["selected"], "together")
        self.assertEqual([p["name"] for p in listed["providers"]], ["together", "claude_code_cli", "floor"])
        self.assertFalse(listed["changed"])

    async def test_opus_moves_claude_first_with_that_model_and_persists(self):
        await self._boot()
        answer = await self._ask(provider="opus", persist=True)
        self.assertTrue(answer["changed"], answer)
        self.assertEqual(answer["selected"], "claude_code_cli")
        self.assertEqual(self.claude.model, "opus")
        self.assertEqual(await self._think(), "claude_code_cli")
        written = tomllib.loads(self.toml.read_text())
        self.assertEqual(written["cognition"]["provider_order"][0], "claude_code_cli")
        self.assertEqual(written["cognition"]["providers"]["claude_code_cli"]["model"], "opus")
        self.assertEqual(written["voice"]["tts"], "elevenlabs", "every other setting kept")

    async def test_a_model_name_finds_its_provider_and_nonsense_is_refused(self):
        await self._boot()
        self.assertEqual((await self._ask(provider="claude_code_cli"))["selected"], "claude_code_cli")
        self.assertEqual((await self._ask(provider="GLM-5.3-Flash"))["selected"], "together")
        refused = await self._ask(provider="gpt-9")
        self.assertIn("no provider or model called 'gpt-9'", refused["refused"])
        self.assertFalse(refused["changed"])
        self.assertFalse(self.toml.read_text().count("provider_order"), "nothing persisted without persist")


class ClaudeCliModel(unittest.TestCase):
    def test_a_named_model_is_passed_as_model(self):
        seen = []

        def runner(argv, **kw):
            seen.append(argv)
            raise OSError("not really run")

        provider = ClaudeCodeProvider(runner=runner, binary="sh", model="opus")
        self.assertEqual(provider.model, "opus")
        with self.assertRaises(Exception):
            provider._complete_sync("hi", "", 1.0)  # noqa: SLF001
        self.assertEqual(seen[0][seen[0].index("--model") + 1], "opus")
        provider.set_model("")
        self.assertEqual(provider.model, ClaudeCodeProvider.UNNAMED)


if __name__ == "__main__":
    unittest.main()
