"""Stage 2 item 4: native tool calling, one recorded fixture per dialect."""

import json
import unittest

from simorgh.cognition.providers import native
from simorgh.cognition.providers.gemini import GeminiProvider
from simorgh.cognition.providers.together import TogetherProvider

TOOLS = [
    {"name": "read_file", "description": "Read a file.",
     "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}},
    {"name": "skill:greet", "description": "Greet someone.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False}},
]


class TogetherSpeaksOpenAITools(unittest.TestCase):
    def _provider(self, reply):
        sent = {}

        def transport(url, headers, payload, timeout):
            sent.update(json.loads(payload))
            return json.dumps(reply)

        return TogetherProvider(api_key="k", transport=transport), sent

    def test_the_request_carries_function_specs_with_wire_names(self):
        provider, sent = self._provider({"choices": [{"message": {"content": "hi"}}], "usage": {}})
        provider._complete_sync([{"role": "user", "content": "hello"}], 100, 5.0, TOOLS)  # noqa: SLF001
        self.assertEqual(sent["tool_choice"], "auto")
        names = [t["function"]["name"] for t in sent["tools"]]
        self.assertEqual(names, ["read_file", "skill__greet"])
        self.assertEqual(sent["tools"][0]["function"]["parameters"]["required"], ["path"])

    def test_no_tools_means_no_tools_key(self):
        provider, sent = self._provider({"choices": [{"message": {"content": "hi"}}], "usage": {}})
        provider._complete_sync([{"role": "user", "content": "hello"}], 100, 5.0, None)  # noqa: SLF001
        self.assertNotIn("tools", sent)

    def test_calls_come_back_with_sim_names_and_a_bad_one_is_an_error_not_a_crash(self):
        reply = {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "skill__greet", "arguments": '{"name": "Ira"}'}},
            {"id": "c2", "type": "function", "function": {"name": "read_file", "arguments": "{not json"}},
        ]}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        provider, _ = self._provider(reply)
        response = provider._complete_sync([{"role": "user", "content": "x"}], 100, 5.0, TOOLS)  # noqa: SLF001
        self.assertEqual(response.text, "")
        first, second = response.tool_calls
        self.assertEqual((first["id"], first["tool"], first["args"]), ("c1", "skill:greet", {"name": "Ira"}))
        self.assertEqual(second["tool"], "read_file")
        self.assertIn("malformed arguments", second["error"])

    def test_typed_tool_turns_go_out_as_openai_messages(self):
        out = native.openai_messages([
            {"role": "user", "content": "read x"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "tool": "read_file", "args": {"path": "x"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "hello"},
        ])
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "tool"])
        self.assertEqual(out[1]["tool_calls"][0]["function"]["arguments"], '{"path": "x"}')
        self.assertEqual(out[2]["tool_call_id"], "c1")


class GeminiSpeaksFunctionDeclarations(unittest.TestCase):
    def test_declarations_go_in_config_and_calls_come_back(self):
        seen = {}

        class _Call:
            def __init__(self, name, args):
                self.name, self.args, self.id = name, args, None

        class _Response:
            function_calls = [_Call("skill__greet", {"name": "Aran"}), _Call("read_file", "oops")]
            usage_metadata = None
            candidates = []

            @property
            def text(self):
                raise ValueError("function call only")

        class _Models:
            def generate_content(self, *, model, contents, config=None):
                seen["config"] = config
                return _Response()

        class _Client:
            models = _Models()

        provider = GeminiProvider(api_key="k", client=_Client())
        response = provider._complete_sync("hi", 100, 5.0, TOOLS)  # noqa: SLF001
        decls = seen["config"]["tools"][0]["function_declarations"]
        self.assertEqual([d["name"] for d in decls], ["read_file", "skill__greet"])
        self.assertNotIn("additionalProperties", decls[1]["parameters"])
        # Property names survive; only schema keywords are filtered (live 400, 2026-09-19).
        self.assertEqual(decls[0]["parameters"]["properties"], {"path": {"type": "string"}})
        self.assertEqual(decls[0]["parameters"]["required"], ["path"])
        self.assertEqual(seen["config"]["automatic_function_calling"], {"disable": True})
        self.assertEqual(response.tool_calls[0]["tool"], "skill:greet")
        self.assertEqual(response.tool_calls[0]["args"], {"name": "Aran"})
        self.assertIn("error", response.tool_calls[1])
