"""`remember`: keeping one fact on purpose (execution/tools.py).

The missing half of `memory_forget`. A chat turn could be told to forget
something forever -- `memory_forget` is `irreversible` -- and had no way
at all to be told to remember something forever: its tools were
`memory_search` (read), `memory_forget` (delete) and
`kb_search`/`kb_ask`/`kb_open` (read). Nothing stored.

The gap hides most of the time, because Memory records every turn by
itself (`Memory._on_turn_completed` is the only thing in the system that
writes episodic memory) so the model cannot forget to remember a
conversation. It bit on a fact Sim had WORKED OUT: the creator, on
2026-09-24, asked it to keep his son's school calendar after reading it
off the school's website. Sim reached for `overheard_note` -- the
48-hour voice-memo store, whose description then claimed it "keeps
something on purpose" -- and then offered to queue a whole task to write
a file. The calendar was in episodic memory throughout, as the words of
one turn among hundreds, ranked no higher than small talk.
"""

from __future__ import annotations

import types
import unittest

from simorgh.execution.config import Config
from simorgh.execution.tools import RememberTool


class _Bus:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, message):
        self.published.append({"type": message.type, **dict(message.payload)})


class RememberTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bus = _Bus()
        self.tool = RememberTool(Config())
        self.ctx = types.SimpleNamespace(bus=self.bus, task_id="t1")

    async def test_a_fact_goes_to_memory_as_semantic_and_confident(self):
        result = await self.tool.run({"fact": "Aran's school year at Mitty starts 18 August 2026."},
                                     ctx=self.ctx)
        self.assertTrue(result.ok)
        sent = self.bus.published[-1]
        # `semantic`, not `episodic`: consolidation keeps and ranks this
        # kind, and the point is to outlive the transcript it was said in.
        self.assertEqual(sent["kind"], "semantic")
        self.assertEqual(sent["confidence"], RememberTool.CONFIDENCE)
        self.assertIn("18 August 2026", sent["content"])
        self.assertIn("remembered", sent["tags"])
        self.assertEqual(sent["source_ref"], "t1")

    async def test_it_says_it_was_handed_over_not_that_it_is_saved(self):
        """`memory.store` has no reply in the catalogue, so this tool
        publishes and cannot know the outcome. Claiming "saved" would be
        a promise about another subsystem's work."""
        result = await self.tool.run({"fact": "The bins go out on Tuesday."}, ctx=self.ctx)
        self.assertIn("handed to memory", result.output)
        self.assertNotIn("saved", result.output)

    async def test_an_empty_fact_is_refused_and_nothing_is_stored(self):
        for args in ({}, {"fact": "   "}):
            result = await self.tool.run(args, ctx=self.ctx)
            self.assertFalse(result.ok)
            self.assertIn("required", result.error)
        self.assertEqual(self.bus.published, [])

    async def test_a_document_sized_fact_is_refused_and_says_where_it_belongs(self):
        result = await self.tool.run({"fact": "x " * RememberTool.MAX_CHARS}, ctx=self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("knowledge base", result.error)
        self.assertEqual(self.bus.published, [])

    async def test_tags_are_taken_however_they_are_written(self):
        await self.tool.run({"fact": "Ira's birthday is in May.", "tags": "family, dates"}, ctx=self.ctx)
        self.assertEqual(sorted(self.bus.published[-1]["tags"]), ["dates", "family", "remembered"])

    async def test_without_a_bus_it_says_so_rather_than_pretending(self):
        result = await self.tool.run({"fact": "anything"}, ctx=types.SimpleNamespace(bus=None))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "unconfigured")

    def test_it_is_reversible_because_memory_forget_takes_it_back(self):
        self.assertEqual(self.tool.reversibility, "reversible")
        self.assertFalse(self.tool.read_only)

    def test_both_chat_profiles_offer_it(self):
        """A tool no conversation can reach would not have closed the gap."""
        from simorgh.orchestration import profiles

        for profile in (profiles.CHAT, profiles.VOICE_CHAT):
            self.assertIn("remember", profile.tools)

    def test_the_memo_tool_no_longer_claims_to_be_memory(self):
        """What actually misled Sim was a description, not a missing
        tool: `overheard_note` said it "keeps something on purpose"."""
        from simorgh.execution.tools import OverheardNoteTool
        from simorgh.orchestration.scaffolds import _TOOL_NOTES

        for text in (OverheardNoteTool.description, _TOOL_NOTES["overheard_note"]):
            self.assertIn("48 hours", text)
            self.assertIn("remember", text)
