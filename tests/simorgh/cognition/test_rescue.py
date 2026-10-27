"""Stage 16 item 1: rescue parsing. Fixtures follow forge's own
(`tests/unit/test_templates.py`, MIT), renamed to Sim's tools where the
point is the parser's wiring."""

import dataclasses
import unittest

from simorgh.cognition.api import Capabilities
from simorgh.cognition.config import Config, ProviderConfig
from simorgh.cognition.parser import OutputParser
from simorgh.cognition.rescue import rescue_tool_calls, strip_think
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse

from .test_service import CognitionServiceTestCase


def _sig(calls):
    return [(c["tool"], c["args"]) for c in calls]


class EachStrategy(unittest.TestCase):
    CASES = [
        ("forge JSON", '{"tool": "fetch", "args": {"part": "X123"}}', [("fetch", {"part": "X123"})]),
        ("JSON fence", '```json\n{"tool": "fetch", "args": {"part": "X"}}\n```', [("fetch", {"part": "X"})]),
        ("bare fence", '```\n{"tool": "fetch", "args": {}}\n```', [("fetch", {})]),
        ("JSON in prose", 'I will call: {"tool": "fetch", "args": {"key": "val"}}', [("fetch", {"key": "val"})]),
        ("nested JSON", 'Calling: {"tool": "fetch", "args": {"filter": {"type": "active"}}}.',
         [("fetch", {"filter": {"type": "active"}})]),
        ("OpenAI keys", '{"name": "fetch", "arguments": {"part": "X123"}}', [("fetch", {"part": "X123"})]),
        ("OpenAI string arguments", '{"name": "fetch", "arguments": "{\\"part\\": \\"X\\"}"}',
         [("fetch", {"part": "X"})]),
        ("tool_call wrapper", '<tool_call>{"name": "fetch", "arguments": {"part": "X"}}</tool_call>',
         [("fetch", {"part": "X"})]),
        ("missing args", '{"tool": "fetch"}', [("fetch", {})]),
        ("brace inside a string", '{"tool": "fetch", "args": {"q": "a } b"}}', [("fetch", {"q": "a } b"})]),
        ("multiple JSON calls", '{"tool": "fetch", "args": {"part": "A"}} {"tool": "submit", "args": {"q": "B"}}',
         [("fetch", {"part": "A"}), ("submit", {"q": "B"})]),
        ("rehearsal", 'fetch[ARGS]{"key": "value"}', [("fetch", {"key": "value"})]),
        ("rehearsal after bracket thinking", '[THINK]reasoning[/THINK] submit[ARGS]{"findings": "data"}',
         [("submit", {"findings": "data"})]),
        ("rehearsal after XML thinking", '<think>reasoning</think> fetch[ARGS]{"id": 42}', [("fetch", {"id": 42})]),
        ("Qwen parameters", "<function=fetch>\n<parameter=query>hello</parameter>\n"
         "<parameter=limit>10</parameter>\n</function>", [("fetch", {"query": "hello", "limit": "10"})]),
        ("Qwen multiline", '<function=fetch>\n<parameter=command>\nfind . -name "*.py" -exec grep -l x {} \\;\n'
         "</parameter>\n</function>", [("fetch", {"command": 'find . -name "*.py" -exec grep -l x {} \\;'})]),
        ("multiple Qwen calls", "<function=fetch><parameter=q>one</parameter></function>\n"
         "<function=submit><parameter=data>two</parameter></function>",
         [("fetch", {"q": "one"}), ("submit", {"data": "two"})]),
        ("Qwen after thinking", "<think>r</think><function=fetch><parameter=query>w</parameter></function>",
         [("fetch", {"query": "w"})]),
        ("Mistral", '[TOOL_CALLS]fetch{"file_path": "t.py"}', [("fetch", {"file_path": "t.py"})]),
        ("Mistral space", '[TOOL_CALLS]fetch {"file_path": "t.py"}', [("fetch", {"file_path": "t.py"})]),
        ("Mistral newline", '[TOOL_CALLS]fetch\n{"file_path": "t.py"}', [("fetch", {"file_path": "t.py"})]),
        ("Mistral nested braces", '[TOOL_CALLS]submit{"old": "if x: { print(1) }"}',
         [("submit", {"old": "if x: { print(1) }"})]),
        ("Mistral escaped quote", '[TOOL_CALLS]submit{"old": "say \\"hi\\""}', [("submit", {"old": 'say "hi"'})]),
        ("multiple Mistral", '[TOOL_CALLS]fetch{"p": "a"}\n[TOOL_CALLS]fetch{"p": "b"}',
         [("fetch", {"p": "a"}), ("fetch", {"p": "b"})]),
        ("Mistral after apology and thinking", 'I apologize.\n<think>read first</think>\n[TOOL_CALLS]fetch{"p": "x"}',
         [("fetch", {"p": "x"})]),
        ("name case folded to the offered spelling", '{"tool": "FETCH", "args": {}}', [("fetch", {})]),
    ]

    def test_matrix(self):
        for label, text, expected in self.CASES:
            calls = rescue_tool_calls(text, ["fetch", "submit"])
            self.assertEqual(_sig(calls), expected, label)
            self.assertTrue(all(c["rescued"] is True and "id" not in c for c in calls), label)

    def test_precedence_is_forges(self):
        for tail in ('submit[ARGS]{"source": "rehearsal"}',
                     "<function=submit><parameter=source>qwen</parameter></function>",
                     '[TOOL_CALLS]submit{"source": "mistral"}'):
            text = '{"tool": "fetch", "args": {"source": "json"}} ' + tail
            self.assertEqual(_sig(rescue_tool_calls(text, ["fetch", "submit"])), [("fetch", {"source": "json"})], tail)

    def test_think_tags_are_stripped(self):
        self.assertEqual(strip_think("<think>a</think> b [THINK]c[/THINK]"), "b")


class NothingIsRescued(unittest.TestCase):
    def test_negative_matrix(self):
        for label, text in [
            ("unknown JSON", '{"tool": "delete_everything", "args": {}}'),
            ("unknown rehearsal", 'unknown[ARGS]{"force": true}'),
            ("malformed rehearsal", "fetch[ARGS]{bad json}"),
            ("unknown Qwen", "<function=unknown><parameter=x>1</parameter></function>"),
            ("unclosed Qwen", "<function=fetch><parameter=q>never closed"),
            ("unknown Mistral", '[TOOL_CALLS]unknown{"x": 1}'),
            ("unclosed Mistral", '[TOOL_CALLS]fetch{"x": "never closed"'),
            ("malformed JSON", '{"tool": "fetch", "args": {bad json}'),
            ("unsupported keys", '{"function": "fetch", "params": {}}'),
            ("args not an object", '{"tool": "fetch", "args": ["a", "b"]}'),
            ("string args not an object", '{"name": "fetch", "arguments": "a.py"}'),
            ("Mistral args a list", '[TOOL_CALLS]fetch["a"]'),
            ("plain text", "Analyze the data first."),
            ("empty", ""),
            ("thinking only", "[THINK]just thinking[/THINK]"),
            ("call only inside thinking", '<think>{"tool": "fetch", "args": {}}</think>The answer is 4.'),
        ]:
            self.assertEqual(rescue_tool_calls(text, ["fetch", "submit"]), (), label)

    def test_a_tool_not_offered_is_never_rescued(self):
        text = '{"tool": "run_shell", "args": {"argument": "rm -rf /"}}'
        self.assertEqual(rescue_tool_calls(text, ["read_file"]), ())
        self.assertEqual(rescue_tool_calls(text, []), ())
        self.assertEqual(rescue_tool_calls('[TOOL_CALLS]run_shell{"a": 1}', ["read_file"]), ())

    def test_prose_mentioning_a_tool_is_not_rescued(self):
        for text in (
            "I could use read_file to look at it, but the answer is already clear.",
            "The read_file tool reads a file; web_search searches the web.",
            "Try read_file(path) next time.",
            "read_file[ARGS] is how I would write it.",
        ):
            self.assertEqual(rescue_tool_calls(text, ["read_file", "web_search"]), (), text)


MARKERS = ("read_file", "web_search", "run_shell")
SPEC = {"kind": "markers", "markers": MARKERS}


class TheParser(unittest.TestCase):
    def test_a_rescued_call_is_marked(self):
        parsed = OutputParser().parse('Sure.\n```json\n{"tool": "read_file", "args": {"path": "a.py"}}\n```', SPEC)
        self.assertEqual(parsed.kind, "tool_calls")
        self.assertTrue(parsed.rescued)
        self.assertEqual(parsed.tool_calls, ({"tool": "read_file", "args": {"path": "a.py"}, "rescued": True},))

    def test_a_well_formed_marker_is_unchanged(self):
        parsed = OutputParser().parse('READ_FILE: a.py', SPEC)
        self.assertFalse(parsed.rescued)
        self.assertEqual(parsed.tool_calls, ({"tool": "read_file", "args": {"argument": "a.py"}},))

    def test_a_marker_wins_over_json_in_the_same_reply(self):
        parsed = OutputParser().parse('READ_FILE: a.py\n{"tool": "web_search", "args": {"q": "x"}}', SPEC)
        self.assertFalse(parsed.rescued)
        self.assertEqual(parsed.tool_calls[0]["tool"], "read_file")

    def test_plain_prose_stays_a_final_answer(self):
        parsed = OutputParser().parse("I could use read_file, but it is 4.", SPEC)
        self.assertEqual((parsed.kind, parsed.rescued, parsed.tool_calls), ("final", False, ()))

    def test_a_final_expectation_is_never_rescued(self):
        parsed = OutputParser().parse('{"tool": "read_file", "args": {}}', {"kind": "final"})
        self.assertEqual(parsed.kind, "final")

    def test_strict_skips_rescue(self):
        parsed = OutputParser(strict=True).parse('{"tool": "read_file", "args": {"path": "a.py"}}', SPEC)
        self.assertEqual((parsed.kind, parsed.rescued), ("final", False))


class _Native:
    capabilities = Capabilities(supports_tools=True)

    def __init__(self, name, calls, text=""):
        self.name, self._calls, self._text = name, calls, text

    def available(self):
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        return ProviderResponse(text=self._text, provider=self.name, tool_calls=self._calls, cost_usd=0.0)


class TheService(CognitionServiceTestCase):
    async def _think(self, calls, text="", ablate=()):
        provider = _Native("p", calls, text)
        base = Config()
        config = dataclasses.replace(base, provider_order=("p", "floor"), assembly_request_timeout=0.05,
                                     ablate=ablate, providers={**base.providers, "p": ProviderConfig(
                                         max_calls=10, window_seconds=3600.0, tool_dialect="native")})
        await self._make(providers=[provider], config=config)
        reply = await self.bus.request(Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "read the readme"}],
            "tools": ["read_file"], "expected": "tool_calls",
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
        }), timeout=5.0)
        return reply.payload

    QWEN = "<function=read_file><parameter=path>README.md</parameter></function>"

    async def test_a_native_reply_with_no_typed_call_is_rescued(self):
        payload = await self._think((), text=self.QWEN)
        self.assertEqual(payload["tool_calls"], [{"tool": "read_file", "args": {"path": "README.md"}, "rescued": True}])

    async def test_a_typed_native_call_is_unchanged(self):
        good = ({"id": "c1", "tool": "read_file", "args": {"path": "README.md"}},)
        payload = await self._think(good, text=self.QWEN)
        self.assertEqual(payload["tool_calls"], [{"tool": "read_file", "args": {"path": "README.md"}, "id": "c1"}])

    async def test_ablated_rescue_leaves_it_text(self):
        payload = await self._think((), text=self.QWEN, ablate=("rescue",))
        self.assertEqual(payload["tool_calls"], [])


if __name__ == "__main__":
    unittest.main()
