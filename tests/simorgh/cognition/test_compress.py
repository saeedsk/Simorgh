"""Stage 17 item 4: long tool results compressed with LLMLingua-2
(`cognition/compress.py`), behind `[cognition] compress_tool_results`.

`llmlingua` is not installed here; a fake module is put in
`sys.modules` for the tests that need one, and `sys.modules["llmlingua"]
= None` stands for "not installed" whatever the machine has."""

from __future__ import annotations

import dataclasses
import sys
import time
import types
import unittest
from unittest import mock

from simorgh.cognition import compress
from simorgh.cognition.compress import MIN_RUN_CHARS, Compressor, has_farsi, segments
from simorgh.cognition.config import ABLATE_SWITCHES, Config as CognitionConfig, ProviderConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

from . import test_service as _svc   # a module, so pytest does not collect its tests here again
from . import test_token_split as _split

PROSE = ("The quick brown fox jumps over the lazy dog while the committee reviews "
         "the quarterly figures and notes a modest rise in returns. ") * 40          # ~5,000 chars
CODE = "```python\ndef keep_me(x):\n    return x * 42  # exact\n```"
FARSI = "این متن فارسی است و نباید فشرده شود، چون سیم آن را بلند می‌خواند. " * 6
RESULT = f"Result of web_fetch:\n{PROSE}\n\n{CODE}\n\n{FARSI}\n\n{PROSE}"


def _halve(text: str) -> str:
    return "\n".join(" ".join(line.split(" ")[::2]) for line in text.split("\n"))


class _FakePromptCompressor:
    calls: list[str] = []
    delay = 0.0
    raises: Exception | None = None

    def __init__(self, model_name="", use_llmlingua2=False, device_map=""):
        self.model_name, self.use_llmlingua2 = model_name, use_llmlingua2

    def compress_prompt(self, text, rate=0.5, **kwargs):
        type(self).calls.append(text)
        if type(self).delay:
            time.sleep(type(self).delay)
        if type(self).raises is not None:
            raise type(self).raises
        return {"compressed_prompt": _halve(text), "rate": rate}


class _FakeModule:
    """Puts a fake `llmlingua` in `sys.modules`, or None for "absent"."""

    def __init__(self, present: bool = True):
        self.present = present

    def __enter__(self):
        self._saved = sys.modules.get("llmlingua", _MISSING)
        _FakePromptCompressor.calls = []
        _FakePromptCompressor.delay = 0.0
        _FakePromptCompressor.raises = None
        if self.present:
            module = types.ModuleType("llmlingua")
            module.PromptCompressor = _FakePromptCompressor
            sys.modules["llmlingua"] = module
        else:
            sys.modules["llmlingua"] = None
        return _FakePromptCompressor

    def __exit__(self, *exc):
        if self._saved is _MISSING:
            sys.modules.pop("llmlingua", None)
        else:
            sys.modules["llmlingua"] = self._saved


_MISSING = object()


def _messages(result: str = RESULT) -> list[dict]:
    long_other = "x " * 3_000
    return [
        {"role": "system", "content": "Things you remember:\n" + long_other},          # memory: never
        {"role": "user", "content": "summarise that page " + long_other, "protected": True},
        {"role": "assistant", "content": "WEB_FETCH: https://example.com/" + "a" * 4_500},  # a call: never
        {"role": "user", "content": result},                                            # long result
        {"role": "user", "content": "Result of read_file:\n" + "short " * 20},          # short result
    ]


class Segments(unittest.TestCase):
    def test_pieces_join_back_to_the_text(self):
        pieces = segments(RESULT)
        self.assertEqual("".join(p for p, _ in pieces), RESULT)

    def test_code_farsi_json_and_headers_are_never_compressible(self):
        pieces = segments(RESULT + '\n\n{"rows": [1, 2, 3]}\n\n    indented()\n    code()')
        compressible = [p for p, ok in pieces if ok]
        self.assertEqual(len(compressible), 2)
        for p in compressible:
            self.assertNotIn("```", p)
            self.assertFalse(has_farsi(p))
            self.assertNotIn("Result of", p)
            self.assertNotIn('"rows"', p)
            self.assertNotIn("indented()", p)

    def test_a_short_run_is_left_alone(self):
        self.assertEqual(segments("x" * (MIN_RUN_CHARS - 10)), [("x" * (MIN_RUN_CHARS - 10), False)])


class TheCompressor(unittest.IsolatedAsyncioTestCase):
    async def test_only_long_tool_results_are_compressed(self):
        with _FakeModule() as fake:
            compressor = Compressor(rate=0.5, min_chars=4_000, timeout_s=5.0)
            try:
                messages = _messages()
                out, stats = await compressor.compress_messages(messages)
            finally:
                compressor.close()
        self.assertEqual(stats.outcome, "compressed")
        self.assertEqual(stats.results, 1)
        self.assertGreater(stats.chars_in, stats.chars_out)
        self.assertGreaterEqual(stats.ms, 0.0)
        for i in (0, 1, 2, 4):
            self.assertIs(out[i], messages[i])
        self.assertLess(len(out[3]["content"]), len(RESULT))
        # Code and Farsi reach the model exactly; the header line too.
        self.assertIn(CODE, out[3]["content"])
        self.assertIn(FARSI.strip(), out[3]["content"])
        self.assertTrue(out[3]["content"].startswith("Result of web_fetch:\n"))
        for text in fake.calls:
            self.assertNotIn("```", text)
            self.assertFalse(has_farsi(text))
        self.assertEqual(messages[3]["content"], RESULT)   # the caller's list is not mutated

    async def test_a_typed_tool_message_is_a_result_too(self):
        with _FakeModule():
            compressor = Compressor(timeout_s=5.0)
            try:
                messages = [{"role": "tool", "tool_call_id": "c1", "content": PROSE}]
                out, stats = await compressor.compress_messages(messages)
            finally:
                compressor.close()
        self.assertEqual(stats.outcome, "compressed")
        self.assertEqual(out[0]["tool_call_id"], "c1")
        self.assertLess(len(out[0]["content"]), len(PROSE))

    async def test_protected_and_load_bearing_results_are_left_alone(self):
        with _FakeModule() as fake:
            compressor = Compressor(timeout_s=5.0)
            try:
                messages = [{"role": "user", "content": RESULT, "load_bearing": True},
                            {"role": "user", "content": RESULT, "protected": True}]
                out, stats = await compressor.compress_messages(messages)
            finally:
                compressor.close()
        self.assertIs(out, messages)
        self.assertEqual(stats.outcome, "skipped")
        self.assertEqual(fake.calls, [])

    async def test_a_timeout_sends_the_original(self):
        with _FakeModule() as fake:
            fake.delay = 0.5
            compressor = Compressor(timeout_s=0.05)
            try:
                messages = _messages()
                started = time.perf_counter()
                out, stats = await compressor.compress_messages(messages)
                waited = time.perf_counter() - started
            finally:
                compressor.close()
        self.assertIs(out, messages)
        self.assertEqual(stats.outcome, "timeout")
        self.assertLess(waited, 0.4)

    async def test_an_error_sends_the_original(self):
        with _FakeModule() as fake:
            fake.raises = RuntimeError("model fell over")
            compressor = Compressor(timeout_s=5.0)
            try:
                messages = _messages()
                out, stats = await compressor.compress_messages(messages)
            finally:
                compressor.close()
        self.assertIs(out, messages)
        self.assertEqual(stats.outcome, "error")

    def test_an_absent_package_is_unavailable_by_name(self):
        with _FakeModule(present=False):
            compressor = Compressor()
            try:
                why = compressor.unavailable()
            finally:
                compressor.close()
        self.assertIn("compress", why)
        self.assertIn("llmlingua", why)

    def test_a_present_package_is_available(self):
        with _FakeModule():
            compressor = Compressor()
            try:
                self.assertEqual(compressor.unavailable(), "")
            finally:
                compressor.close()


class TheConfig(unittest.TestCase):
    def test_defaults_are_off(self):
        cfg = CognitionConfig()
        self.assertFalse(cfg.compress_tool_results)
        self.assertEqual(cfg.compress_min_chars, 4_000)
        self.assertEqual(cfg.compress_rate, 0.5)

    def test_keys_are_read(self):
        cfg = CognitionConfig.from_mapping({"compress_tool_results": True, "compress_min_chars": 6000,
                                            "compress_rate": 0.33, "ablate": ["compress"]})
        self.assertTrue(cfg.compress_tool_results)
        self.assertEqual((cfg.compress_min_chars, cfg.compress_rate), (6000, 0.33))
        self.assertEqual(cfg.ablate, ("compress",))
        self.assertEqual(cfg.problems, ())
        self.assertIn("compress", ABLATE_SWITCHES)

    def test_a_string_switch_is_a_problem_and_off(self):
        cfg = CognitionConfig.from_mapping({"compress_tool_results": "yes"})
        self.assertFalse(cfg.compress_tool_results)
        self.assertEqual(len(cfg.problems), 1)


class TheServiceSends(unittest.IsolatedAsyncioTestCase):
    # The service harness of test_service.py, without inheriting its tests.
    _make = _svc.CognitionServiceTestCase._make

    async def _think(self, **overrides):
        provider = _svc._FakeProvider("fake_llm")
        config = dataclasses.replace(CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
            providers={**CognitionConfig().providers,
                       "fake_llm": ProviderConfig(max_calls=10, window_seconds=3600.0)}), **overrides)
        await self._make(providers=[provider], config=config)
        telemetry = _split._Telemetry()
        self.service._ctx = dataclasses.replace(self.ctx, telemetry=telemetry)
        messages = [{"role": "user", "content": "summarise that page", "protected": True},
                    {"role": "assistant", "content": "WEB_FETCH: https://example.com"},
                    {"role": "user", "content": RESULT}]
        reply = await self.bus.request(Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "research", "messages": messages, "tools": ["web_fetch"], "expected": "tool_calls",
            "budget": {"max_tokens": 500, "max_cost_usd": 0.1}, "require_real_provider": False,
        }), timeout=10.0)
        self.assertNotIn("error", reply.payload)
        (span,) = [s for s in telemetry.spans if s.name == "cognition.provider_call"]
        health = await self.service.health()
        self.problems = self.service._config.problems
        await self.asyncTearDown()
        return provider.received_messages, span.attrs, health

    async def test_off_is_byte_identical_and_records_nothing(self):
        with _FakeModule() as fake:
            default, default_attrs, _ = await self._think()
            off, off_attrs, _ = await self._think(compress_tool_results=False)
            ablated, ablated_attrs, _ = await self._think(compress_tool_results=True, ablate=("compress",))
            self.assertEqual(fake.calls, [])
        self.assertEqual(off, default)
        self.assertEqual(ablated, default)
        self.assertTrue(any(RESULT in m["content"] for m in default))
        for attrs in (default_attrs, off_attrs, ablated_attrs):
            self.assertNotIn("compress", attrs)

    async def test_on_compresses_the_result_and_the_span_says_how_much(self):
        with _FakeModule():
            default, _, _ = await self._think()
            on, attrs, _ = await self._think(compress_tool_results=True)
        self.assertNotEqual(on, default)
        self.assertEqual([m["role"] for m in on], [m["role"] for m in default])
        # The system prefix and tool block are what they were.
        self.assertEqual([m for m in on if m["role"] == "system"], [m for m in default if m["role"] == "system"])
        user = next(m["content"] for m in on if m["role"] == "user")
        self.assertNotIn(RESULT, user)
        self.assertIn(CODE, user)
        self.assertIn(FARSI.strip(), user)
        self.assertIn("summarise that page", user)
        record = attrs["compress"]
        self.assertEqual(record["outcome"], "compressed")
        self.assertEqual(record["results"], 1)
        self.assertGreater(record["chars_in"], record["chars_out"])
        self.assertIn("ms", record)

    async def test_absent_package_is_unavailable_and_changes_nothing(self):
        with _FakeModule(present=False):
            default, _, _ = await self._think()
            on, attrs, health = await self._think(compress_tool_results=True)
            problems = self.problems
        self.assertEqual(on, default)
        self.assertNotIn("compress", attrs)
        self.assertTrue(any("compress" in p and "llmlingua" in p for p in problems), problems)
        self.assertEqual(health.status, "ok")
        self.assertIn("llmlingua", health.detail)

    async def test_a_timeout_in_the_service_sends_the_original(self):
        with _FakeModule() as fake:
            default, _, _ = await self._think()
            fake.delay = 0.3       # past TIMEOUT_S, patched to 0.05 here
            with mock.patch.object(compress, "TIMEOUT_S", 0.05):
                on, attrs, _ = await self._think(compress_tool_results=True)
        self.assertEqual(on, default)
        self.assertEqual(attrs["compress"]["outcome"], "timeout")

    async def asyncTearDown(self):
        # `_think` tears each service down itself; a second stop is harmless
        # only once, so guard it.
        if getattr(self, "service", None) is not None:
            await _svc.CognitionServiceTestCase.asyncTearDown(self)
            self.service = None


if __name__ == "__main__":
    unittest.main()
