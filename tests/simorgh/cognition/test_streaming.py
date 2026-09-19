"""Stage 3 item 1: a provider's reply as a stream of deltas."""

import json
import unittest

from simorgh.cognition.providers.streaming import ERROR, STOP, TEXT, TOOL_INPUT, TOOL_START, collect
from simorgh.cognition.providers.together import TogetherProvider


def _sse(*chunks):
    return [f"data: {json.dumps(c)}\n" for c in chunks] + ["data: [DONE]\n"]


def _provider(lines):
    return TogetherProvider(api_key="k", stream_transport=lambda url, headers, body, timeout: iter(lines))


class TogetherStreams(unittest.IsolatedAsyncioTestCase):
    async def _deltas(self, lines, tools=None):
        return [d async for d in _provider(lines).stream([{"role": "user", "content": "hi"}], tools=tools, max_tokens=50)]

    async def test_text_arrives_in_pieces_and_usage_at_the_stop(self):
        deltas = await self._deltas(_sse(
            {"choices": [{"delta": {"content": "Hel"}}]}, {"choices": [{"delta": {"content": "lo."}}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3}}))
        self.assertEqual([d.text for d in deltas if d.kind == TEXT], ["Hel", "lo."])
        self.assertEqual(deltas[-1].kind, STOP)
        self.assertEqual(deltas[-1].usage["output_tokens"], 3)

    async def test_a_tool_call_starts_early_and_its_arguments_come_whole_at_the_end(self):
        tools = [{"name": "skill:greet", "input_schema": {"type": "object"}}]
        deltas = await self._deltas(_sse(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "skill__greet", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"name": '}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"Ira"}'}}]}}]}), tools)
        kinds = [d.kind for d in deltas]
        self.assertLess(kinds.index(TOOL_START), kinds.index(TOOL_INPUT))
        start = next(d for d in deltas if d.kind == TOOL_START)
        self.assertEqual((start.tool, start.tool_id), ("skill:greet", "c1"))
        self.assertEqual(next(d for d in deltas if d.kind == TOOL_INPUT).args, {"name": "Ira"})

    async def test_malformed_arguments_are_an_error_delta_not_an_exception(self):
        deltas = await self._deltas(_sse(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": "{not json"}}]}}]}))
        error = next(d for d in deltas if d.kind == ERROR)
        self.assertEqual(error.tool, "read_file")
        self.assertIn("malformed", error.text)

    async def test_collect_rebuilds_a_whole_reply(self):
        stream = _provider(_sse({"choices": [{"delta": {"content": "Hi"}}]},
                                {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})).stream(
            [{"role": "user", "content": "x"}], tools=None, max_tokens=10)
        response = await collect(stream, "together")
        self.assertEqual((response.text, response.output_tokens), ("Hi", 1))


class GeminiStreams(unittest.IsolatedAsyncioTestCase):
    async def test_text_then_a_function_call_then_stop(self):
        from simorgh.cognition.providers.gemini import GeminiProvider

        class _Call:
            def __init__(self, name, args):
                self.name, self.args, self.id = name, args, None

        class _Chunk:
            def __init__(self, text="", calls=()):
                self._text, self.function_calls, self.usage_metadata = text, list(calls), None

            @property
            def text(self):
                return self._text

        class _Models:
            def generate_content_stream(self, *, model, contents, config=None):
                yield _Chunk("Let me ")
                yield _Chunk("look.")
                yield _Chunk(calls=[_Call("read_file", {"path": "a.py"})])

        class _Client:
            models = _Models()

        provider = GeminiProvider(api_key="k", client=_Client())
        deltas = [d async for d in provider.stream([{"role": "user", "content": "x"}],
                                                   tools=[{"name": "read_file"}], max_tokens=50)]
        self.assertEqual("".join(d.text for d in deltas if d.kind == TEXT), "Let me look.")
        self.assertEqual(next(d for d in deltas if d.kind == TOOL_INPUT).args, {"path": "a.py"})
        self.assertEqual(deltas[-1].kind, STOP)
