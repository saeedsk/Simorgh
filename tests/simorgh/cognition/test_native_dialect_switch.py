"""Stage 2 item 9: `tool_dialect = "native"` hands the offered tools' specs
to that provider, and its typed calls are the reply's calls."""

import dataclasses
import unittest

from simorgh.cognition.api import Capabilities
from simorgh.cognition.config import Config as CognitionConfig, ProviderConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse

from .test_service import CognitionServiceTestCase


class _Native:
    capabilities = Capabilities(supports_tools=True)

    def __init__(self, name):
        self.name = name
        self.seen_tools = "unset"

    def available(self):
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        self.seen_tools = tools
        calls = ({"id": "c1", "tool": "read_file", "args": {"path": "docs/README.md"}},) if tools else ()
        return ProviderResponse(text="" if tools else "READ_FILE: docs/README.md", provider=self.name,
                                tool_calls=calls, cost_usd=0.0)


class TheNativeSwitch(CognitionServiceTestCase):
    async def _think(self, dialect):
        provider = _Native("p")
        base = CognitionConfig()
        config = dataclasses.replace(base, provider_order=("p", "floor"), assembly_request_timeout=0.05, providers={
            **base.providers, "p": ProviderConfig(max_calls=10, window_seconds=3600.0, tool_dialect=dialect)})
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
        return provider, reply.payload

    async def test_native_gets_specs_and_its_calls_are_the_calls(self):
        provider, payload = await self._think("native")
        self.assertEqual(provider.seen_tools[0]["name"], "read_file")
        self.assertEqual(provider.seen_tools[0]["input_schema"]["required"], ["path"])
        self.assertEqual(payload["tool_calls"], [{"tool": "read_file", "args": {"path": "docs/README.md"}, "id": "c1"}])

    async def test_markers_is_the_default_and_gets_no_specs(self):
        provider, payload = await self._think("markers")
        self.assertIsNone(provider.seen_tools)
        self.assertEqual(payload["tool_calls"][0]["tool"], "read_file")
        self.assertEqual(payload["tool_calls"][0]["args"], {"argument": "docs/README.md"})


class ANativeProviderGetsTheTypedTranscript(unittest.TestCase):
    """Stage 2 item 5: assistant tool_calls and tool results reach a native
    provider as turns, not flattened into one user message."""

    def test_typed_turns_are_kept_when_nothing_was_compacted(self):
        from types import SimpleNamespace

        from simorgh.cognition.service import _typed_transcript

        messages = [
            {"role": "user", "content": "read a.py"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "tool": "read_file", "args": {"path": "a.py"}}]},
            {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "print(1)"},
            {"role": "user", "content": "next"},
        ]
        out = _typed_transcript("You are Sim.", messages, SimpleNamespace(layers_applied=[]))
        self.assertEqual([m["role"] for m in out], ["system", "user", "assistant", "tool", "user"])
        self.assertEqual(out[3]["tool_call_id"], "c1")
        self.assertIsNone(_typed_transcript("x", messages, SimpleNamespace(layers_applied=["1"])))
        self.assertIsNone(_typed_transcript("x", [{"role": "user", "content": "hi"}], SimpleNamespace(layers_applied=[])))
