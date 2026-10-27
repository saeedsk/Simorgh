"""Stage 14 item 3: `[cognition] ablate = ["rescue"]` makes the parser accept
well-formed tool calls only. Each repair the default parser makes is shown
switched off here, next to the same reply under the default, and the
protocol itself (code-bearing payloads, a preamble line, a tone tag) is
shown to survive the switch."""

import dataclasses
import unittest

from simorgh.cognition.api import Capabilities
from simorgh.cognition.config import Config, ProviderConfig
from simorgh.cognition.parser import OutputParser, accept_native_calls
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse

from .test_service import CognitionServiceTestCase

MARKERS = ("read_file", "web_search", "run_shell")
SPEC = {"kind": "markers", "markers": MARKERS}


def _both(text, spec=SPEC):
    return OutputParser().parse(text, spec), OutputParser(strict=True).parse(text, spec)


class TheConfigKey(unittest.TestCase):
    def test_default_is_empty(self):
        self.assertEqual(Config().ablate, ())
        self.assertEqual(Config.from_mapping({"tool_result_max_tokens": 10}).ablate, ())

    def test_rescue_is_read(self):
        cfg = Config.from_mapping({"ablate": ["rescue"]})
        self.assertEqual(cfg.ablate, ("rescue",))
        self.assertEqual(cfg.problems, ())

    def test_unknown_switches_are_problems_not_a_failed_boot(self):
        cfg = Config.from_mapping({"ablate": ["rescue", "scaffold", {"x": 1}]})
        self.assertEqual(cfg.ablate, ("rescue",))
        self.assertEqual(len(cfg.problems), 2, cfg.problems)
        self.assertIn("'scaffold'", cfg.problems[0])

    def test_a_non_list_is_a_problem(self):
        cfg = Config.from_mapping({"ablate": "rescue"})
        self.assertEqual(cfg.ablate, ())
        self.assertEqual(len(cfg.problems), 1)


class RepairsAreSwitchedOff(unittest.TestCase):
    def assertRescuedOnlyByDefault(self, text):
        lenient, strict = _both(text)
        self.assertEqual(lenient.kind, "tool_calls", lenient)
        self.assertEqual(strict.kind, "final", strict)
        self.assertEqual(strict.tool_calls, ())

    def test_lowercase_marker(self):
        self.assertRescuedOnlyByDefault("read_file: docs/README.md")

    def test_indented_marker(self):
        self.assertRescuedOnlyByDefault("Let me look.\n   READ_FILE: docs/README.md")

    def test_prose_after_a_one_line_argument(self):
        self.assertRescuedOnlyByDefault("READ_FILE: docs/README.md\nThat should tell me what I need.")

    def test_a_second_marker_on_the_same_line(self):
        self.assertRescuedOnlyByDefault("READ_FILE: a.py READ_FILE: a.py")

    def test_a_marker_inside_native_tool_tags(self):
        self.assertRescuedOnlyByDefault("I'll check.<tool_call>WEB_SEARCH: weather</tool_call>")

    def test_code_fence_extraction_for_edit_blocks(self):
        text = "Here it is:\n```python\nprint(1)\n```"
        lenient, strict = _both(text, {"kind": "edit_blocks"})
        self.assertEqual(lenient.text, "print(1)")
        self.assertEqual(strict.text, text)

    def test_a_code_bearing_payload_is_not_cut(self):
        text = "RUN_SHELL: pwd\n[user] Result of run_shell:\n/\nREAD_FILE: a.py"
        lenient, strict = _both(text)
        self.assertEqual(lenient.tool_calls[0]["args"]["argument"], "pwd")
        self.assertEqual(strict.tool_calls[0]["args"]["argument"],
                         "pwd\n[user] Result of run_shell:\n/\nREAD_FILE: a.py")
        self.assertEqual(len(strict.tool_calls), 1)


class TheProtocolSurvives(unittest.TestCase):
    def assertSame(self, text):
        lenient, strict = _both(text)
        self.assertEqual(strict, lenient)

    def test_a_plain_call(self):
        self.assertSame("READ_FILE: docs/README.md")

    def test_a_plain_answer(self):
        self.assertSame("It is sunny today.")

    def test_a_multi_line_code_bearing_payload(self):
        self.assertSame("RUN_SHELL: python3 - <<'EOF'\nprint(1)\nEOF")

    def test_a_preamble_line(self):
        self.assertSame("Let me look.\nREAD_FILE: docs/README.md")

    def test_a_tone_tag(self):
        self.assertSame("[bright] WEB_SEARCH: weather in Toronto")

    def test_several_one_line_calls(self):
        self.assertSame("READ_FILE: a.py\nREAD_FILE: b.py\n\nWEB_SEARCH: x")

    def test_verdicts_and_empty_replies(self):
        for text, spec in (("I think YES", {"kind": "verdict"}), ("", SPEC), ("   ", {"kind": "final"})):
            self.assertEqual(OutputParser(strict=True).parse(text, spec), OutputParser().parse(text, spec))


class NativeCalls(unittest.TestCase):
    SPECS = {"read_file": {"input_schema": {"type": "object", "required": ["path"],
                                            "properties": {"path": {"type": "string"}}}}}

    def _kept(self, call):
        return accept_native_calls((call,), ("read_file",), self.SPECS)

    def test_a_well_formed_call_is_kept(self):
        call = {"id": "c1", "tool": "read_file", "args": {"path": "a.py"}}
        self.assertEqual(self._kept(call), (call,))

    def test_malformed_unknown_or_off_schema_calls_are_dropped(self):
        for call in (
            {"id": "c1", "tool": "read_file", "args": {}, "error": "malformed arguments for read_file: '{'"},
            {"id": "c1", "tool": "delete_everything", "args": {"path": "a.py"}},
            {"id": "c1", "tool": "read_file", "args": {}},
            {"id": "c1", "tool": "read_file", "args": {"path": 3}},
        ):
            self.assertEqual(self._kept(call), (), call)


class _Native:
    capabilities = Capabilities(supports_tools=True)

    def __init__(self, name, calls, text=""):
        self.name, self._calls, self._text = name, calls, text

    def available(self):
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        return ProviderResponse(text=self._text, provider=self.name, tool_calls=self._calls, cost_usd=0.0)


class TheServiceThreadsTheSwitch(CognitionServiceTestCase):
    async def _think(self, ablate, calls, text=""):
        provider = _Native("p", calls, text)
        base = Config()
        config = dataclasses.replace(base, provider_order=("p", "floor"), assembly_request_timeout=0.05,
                                     ablate=ablate, providers={**base.providers, "p": ProviderConfig(
                                         max_calls=10, window_seconds=3600.0, tool_dialect="native")})
        await self._make(providers=[provider], config=config)
        await self.bus.publish(Message.new(topics.TOOL_REGISTERED, source="execution", payload={
            "name": "read_file", "version": "1", "description": "Read a file.", "read_only": True,
            "reversibility": "read_only", "schema_ref": "", "provider": "builtin",
            "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}}))
        reply = await self.bus.request(Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "read the readme"}],
            "tools": ["read_file"], "expected": "tool_calls",
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
        }), timeout=5.0)
        return reply.payload

    BAD = ({"id": "c1", "tool": "read_file", "args": {}, "error": "malformed arguments for read_file: '{'"},)

    async def test_default_hands_a_malformed_native_call_back(self):
        payload = await self._think((), self.BAD)
        self.assertEqual(payload["tool_calls"][0]["error"], self.BAD[0]["error"])

    async def test_rescue_off_makes_it_a_plain_answer(self):
        payload = await self._think(("rescue",), self.BAD, text="I will read it.")
        self.assertEqual(payload["tool_calls"], [])
        self.assertEqual(payload["text"], "I will read it.")

    async def test_rescue_off_keeps_a_well_formed_native_call(self):
        good = ({"id": "c1", "tool": "read_file", "args": {"path": "README.md"}},)
        payload = await self._think(("rescue",), good)
        self.assertEqual(payload["tool_calls"], [{"tool": "read_file", "args": {"path": "README.md"}, "id": "c1"}])

    async def test_rescue_off_reaches_the_marker_parser(self):
        payload = await self._think(("rescue",), (), text="read_file: README.md")
        self.assertEqual(payload["tool_calls"], [])


if __name__ == "__main__":
    unittest.main()
