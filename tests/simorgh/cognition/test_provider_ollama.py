"""The local Ollama fallback (no network: a fake transport)."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

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


class Pictures(unittest.IsolatedAsyncioTestCase):
    """A camera still reaching a model that can actually see it."""

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.still = Path(self.dir.name) / "front-door.jpg"
        self.still.write_bytes(b"\xff\xd8not-really-a-jpeg")
        self.addCleanup(self.dir.cleanup)

    async def test_a_picture_goes_to_the_vision_model_as_base64(self):
        transport = _Transport()
        provider = OllamaProvider("qwen3:4b", vision_model="qwen2.5vl:3b", transport=transport)
        await provider.complete([{"role": "user", "content": "what is happening?"}],
                                tools=None, max_tokens=200, images=[str(self.still)])
        _method, _url, body, _timeout = transport.calls[-1]
        self.assertEqual(body["model"], "qwen2.5vl:3b", "the text model cannot see")
        self.assertEqual(body["messages"][-1]["images"],
                         [base64.b64encode(self.still.read_bytes()).decode("ascii")])

    async def test_pictures_ride_on_the_question_not_the_system_prompt(self):
        transport = _Transport()
        provider = OllamaProvider("qwen3:4b", vision_model="qwen2.5vl:3b", transport=transport)
        await provider.complete(
            [{"role": "system", "content": "you are Sim"}, {"role": "user", "content": "what is happening?"}],
            tools=None, max_tokens=200, images=[str(self.still)])
        _method, _url, body, _timeout = transport.calls[-1]
        self.assertNotIn("images", body["messages"][0])
        self.assertIn("images", body["messages"][1])

    async def test_a_still_that_cannot_be_read_is_one_fewer_angle_not_a_crash(self):
        transport = _Transport()
        provider = OllamaProvider("qwen3:4b", vision_model="qwen2.5vl:3b", transport=transport)
        await provider.complete([{"role": "user", "content": "?"}], tools=None, max_tokens=50,
                                images=[str(self.still), str(self.still.parent / "gone.jpg")])
        _method, _url, body, _timeout = transport.calls[-1]
        self.assertEqual(len(body["messages"][-1]["images"]), 1, "the missing one is dropped, the call still goes")

    async def test_without_a_vision_model_sim_says_so_rather_than_guessing(self):
        provider = OllamaProvider("qwen3:4b", transport=_Transport())
        self.assertFalse(provider.supports_images)
        with self.assertRaises(ProviderUnavailable) as caught:
            await provider.complete([{"role": "user", "content": "?"}], tools=None, max_tokens=50,
                                    images=[str(self.still)])
        self.assertIn("vision_model", str(caught.exception))

    async def test_a_call_with_no_pictures_still_uses_the_text_model(self):
        transport = _Transport()
        provider = OllamaProvider("qwen3:4b", vision_model="qwen2.5vl:3b", transport=transport)
        await provider.complete([{"role": "user", "content": "hi"}], tools=None, max_tokens=50)
        _method, _url, body, _timeout = transport.calls[-1]
        self.assertEqual(body["model"], "qwen3:4b")
        self.assertNotIn("images", body["messages"][-1])


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
