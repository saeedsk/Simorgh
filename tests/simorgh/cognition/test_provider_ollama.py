"""The local Ollama fallback (no network: a fake transport)."""

from __future__ import annotations

import json
import unittest

from simorgh.cognition.api import ProviderUnavailable, Purpose
from simorgh.cognition.config import Config
from simorgh.cognition.providers.base import FloorProvider
from simorgh.cognition.providers.ollama import OllamaProvider
from simorgh.cognition.router import Router
from tests.simorgh.cognition.test_router import _FakeProvider, _budget
from tests.simorgh.helpers import FakeClock


class _Transport:
    def __init__(self, reply=None, fail=None):
        self.calls = []
        self._reply = reply or {"model": "qwen3:4b", "message": {"role": "assistant", "content": "hello"},
                                "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 3}
        self._fail = fail

    def __call__(self, method, url, body, timeout):
        self.calls.append((method, url, json.loads(body) if body else None, timeout))
        if self._fail:
            raise self._fail
        return "{\"version\": \"0.12.0\"}" if url.endswith("/api/version") else json.dumps(self._reply)


class OllamaRequest(unittest.IsolatedAsyncioTestCase):
    async def test_the_request_keeps_the_machine_light(self):
        transport = _Transport()
        provider = OllamaProvider("qwen3:4b", transport=transport)
        response = await provider.complete([{"role": "user", "content": "hi"}], tools=None, max_tokens=512)
        method, url, body, _timeout = transport.calls[-1]
        self.assertEqual((method, url), ("POST", "http://127.0.0.1:11434/api/chat"))
        self.assertEqual(body["keep_alive"], "2m", "unloaded again after a short idle")
        self.assertEqual(body["options"]["num_ctx"], 8192, "a small context window")
        self.assertEqual(body["options"]["num_predict"], 512)
        self.assertFalse(body["stream"]); self.assertFalse(body["think"])
        self.assertEqual((response.text, response.provider, response.cost_usd), ("hello", "ollama", 0.0))
        self.assertEqual((response.input_tokens, response.output_tokens), (12, 3))

    async def test_errors_are_provider_unavailable(self):
        provider = OllamaProvider("qwen3:4b", transport=_Transport(reply={"error": "model not found"}))
        with self.assertRaises(ProviderUnavailable):
            await provider.complete([{"role": "user", "content": "hi"}], tools=None, max_tokens=10)
        down = OllamaProvider("qwen3:4b", transport=_Transport(fail=ConnectionRefusedError("refused")))
        with self.assertRaises(ProviderUnavailable):
            await down.complete([{"role": "user", "content": "hi"}], tools=None, max_tokens=10)

    def test_available_needs_a_model_and_a_running_server(self):
        self.assertFalse(OllamaProvider("", transport=_Transport()).available())
        self.assertTrue(OllamaProvider("qwen3:4b", transport=_Transport()).available())
        self.assertFalse(OllamaProvider("qwen3:4b", transport=_Transport(fail=ConnectionRefusedError())).available())


class OnlyPurposes(unittest.IsolatedAsyncioTestCase):
    async def test_a_provider_limited_to_chat_is_skipped_for_a_draft(self):
        local = _FakeProvider("ollama")
        router = Router([local], {}, FloorProvider(), order=("ollama",), clock=FakeClock(),
                        purpose_filter={"ollama": {"chat"}})
        chat, chat_floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=30.0)
        self.assertEqual((chat.provider, chat_floor), ("ollama", False))
        _draft, draft_floor = await router.complete(Purpose.DRAFT, [], tools=None, budget=_budget(), timeout=30.0)
        self.assertTrue(draft_floor, "a draft goes to the floor, not the local model")

    def test_config_loads(self):
        cfg = Config.from_mapping({"providers": {"ollama": {"model": "qwen3:4b", "only_purposes": ["chat"],
                                                            "keep_alive": "2m", "num_ctx": 8192}}})
        self.assertEqual(cfg.providers["ollama"].model, "qwen3:4b")
        self.assertEqual(list(cfg.providers["ollama"].only_purposes), ["chat"])
        self.assertNotIn("ollama", Config().providers, "not configured by default")


if __name__ == "__main__":
    unittest.main()
