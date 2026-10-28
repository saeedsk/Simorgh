"""Tool awareness (`toolindex.py`, `[orchestration] tool_index`).

Live 2026-10-27, by voice: asked to unsubscribe the creator, Sim said it
had no browser; `browse_page` was registered all along, the voice agent's
list did not name it, and told outright, Sim searched its own code for
it. A turn now sees an index of every tool it may load, loads one with
`tool_more{tool|need}`, and a reply that says "I can't" while a matching
tool exists is nudged once.
"""

from __future__ import annotations

import asyncio
import unittest

from simorgh.orchestration import profiles, toolindex
from simorgh.orchestration.api import Session
from simorgh.orchestration.config import Config
from simorgh.orchestration.session import SessionRunner
from simorgh.orchestration.tools import (_TOOL_POLICY, forget_registered, note_description, note_registered,
                                         offered_tools, register_tool_policy)

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run

LASER = "laser_cut"
LASER_SAYS = "Cut a shape out of plywood with the garage laser cutter. Takes an SVG path."


def _register() -> None:
    """Execution's announcements: the chat and voice agents' tools, a tool
    no agent names (the laser), and a build tool (`apply_source_patch`)."""
    for name in offered_tools(profiles.CHAT.tools) + offered_tools(profiles.VOICE_CHAT.tools):
        note_registered(name)
    for name, says, rev in ((LASER, LASER_SAYS, "reversible"),
                            ("apply_source_patch", "Apply a unified diff to Sim's own source.", "reversible")):
        note_registered(name)
        note_description(name, says)
        register_tool_policy(name, reversibility=rev, provider="builtin")


class _Registered(unittest.TestCase):
    def setUp(self):
        self._policy = dict(_TOOL_POLICY)
        _register()

    def tearDown(self):
        forget_registered()
        _TOOL_POLICY.clear()
        _TOOL_POLICY.update(self._policy)


class TheIndex(_Registered):
    def test_a_registered_tool_no_agent_names_is_loadable_and_a_build_tool_is_not(self):
        loadable = toolindex.loadable(read_only=False, own=profiles.VOICE_CHAT.tools)
        self.assertIn(LASER, loadable)
        self.assertNotIn("apply_source_patch", loadable, "a spoken turn is answered, not built")
        self.assertIn("apply_source_patch", toolindex.loadable(read_only=False, own=profiles.CHAT.tools),
                      "the typed chat agent carries it already")

    def test_a_read_only_agent_may_load_only_read_only_tools(self):
        self.assertNotIn(LASER, toolindex.loadable(read_only=True))

    def test_the_index_has_a_line_per_tool_from_its_description(self):
        note = toolindex.index_note([LASER])
        self.assertTrue(note.startswith(toolindex.INDEX_HEADER))
        self.assertIn(f"- {LASER}: Cut a shape out of plywood with the garage laser cutter.", note)
        self.assertNotIn("SVG", note, "one sentence, not the whole description")
        self.assertEqual(toolindex.index_note([]), "")

    def test_search_finds_by_plain_words_and_finds_nothing_for_nonsense(self):
        self.assertEqual(toolindex.search("cut a star out of plywood", [LASER, "remind"])[:1], [LASER])
        self.assertEqual(toolindex.search("zzz qqq", [LASER, "remind"]), [])


class ClaimsOfInability(unittest.TestCase):
    def test_the_live_replies_are_caught(self):
        for said in ("the button only fires inside a real browser, and I can't click it from here",
                     "That's the honest limit of what I can reach without a browser.",
                     "The browser clicker isn't loaded in this session though, so the unsubscribes still need your click.",
                     "I cannot send mail.", "You'll need to click it yourself.",
                     "متأسفم، نمی‌توانم این کار را انجام بدهم"):
            self.assertTrue(toolindex.claims_inability(said), said)

    def test_a_result_is_not_a_claim(self):
        for said in ("I couldn't find any emails from Temu today.", "The light is on.", "Done, unsubscribed."):
            self.assertFalse(toolindex.claims_inability(said), said)


async def _turn(h, words, script, profile=profiles.VOICE_CHAT, **runner_kw):
    cognition = FakeCognition(h.client("cognition"), script=list(script))
    gx = FakeGuardianExecution(h.client("guardian"))
    await cognition.start()
    await gx.start()
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0,
                           assemble_timeout_s=0.05, **runner_kw)
    session = Session(task_id="t0", kind="chat", mode="execute", profile=profile, user_text=words,
                      channel="voice" if profile is profiles.VOICE_CHAT else "")
    await asyncio.wait_for(runner.run(session, user_text=words), timeout=10)
    await cognition.stop()
    await gx.stop()
    return cognition.calls, gx.proposals, session


def _said(call) -> str:
    return " ".join(str(m.get("content")) for m in call.payload["messages"])


class InATurn(_Registered):
    @run
    async def test_off_changes_nothing(self):
        async with Harness() as h:
            calls, _, _ = await _turn(h, "cut a star out of plywood", [{"text": "sure"}])
        self.assertNotIn("tool_more", calls[0].payload["tools"])
        self.assertNotIn(toolindex.INDEX_HEADER, _said(calls[0]))

    @run
    async def test_on_the_turn_sees_the_index_and_tool_more(self):
        async with Harness() as h:
            calls, _, _ = await _turn(h, "cut a star out of plywood", [{"text": "sure"}], tool_index=True)
        self.assertIn("tool_more", calls[0].payload["tools"])
        self.assertNotIn(LASER, calls[0].payload["tools"])
        said = _said(calls[0])
        self.assertIn(toolindex.INDEX_HEADER, said)
        self.assertIn(f"- {LASER}:", said)
        self.assertNotIn("apply_source_patch", said)
        self.assertEqual(calls[0].payload["task_rules"], calls[0].payload["task_rules"])

    @run
    async def test_tool_more_by_name_is_proposed_and_offers_the_tool_next_step(self):
        script = [{"tool_calls": [{"tool": "tool_more", "args": {"tool": LASER}}]}, {"text": "done"}]
        async with Harness() as h:
            calls, proposals, session = await _turn(h, "cut a star out of plywood", script, tool_index=True)
        self.assertEqual([p.payload["args"] for p in proposals], [{"tool": LASER}])
        self.assertIn(LASER, calls[1].payload["tools"])
        self.assertEqual(session.extra_tools, [LASER])
        latest = str(calls[1].payload["messages"][-1].get("content"))
        self.assertIn(toolindex.INDEX_HEADER, latest)
        index = latest.split(toolindex.INDEX_HEADER)[-1].split("\n\n")[0]
        self.assertNotIn(f"- {LASER}:", index, "a loaded tool leaves the index")

    @run
    async def test_tool_more_by_need_searches(self):
        script = [{"tool_calls": [{"tool": "tool_more", "args": {"need": "cut plywood with a laser"}}]},
                  {"text": "done"}]
        async with Harness() as h:
            calls, _, _ = await _turn(h, "cut a star out of plywood", script, tool_index=True)
        self.assertIn(LASER, calls[1].payload["tools"])

    @run
    async def test_a_build_tool_is_refused_and_never_proposed(self):
        script = [{"tool_calls": [{"tool": "tool_more", "args": {"tool": "apply_source_patch"}}]}, {"text": "ok"}]
        async with Harness() as h:
            calls, proposals, session = await _turn(h, "fix your code", script, tool_index=True)
        self.assertEqual(proposals, [])
        self.assertNotIn("apply_source_patch", calls[1].payload["tools"])
        self.assertIn("no tool called 'apply_source_patch'", _said(calls[1]))

    @run
    async def test_saying_it_cannot_while_a_tool_can_gets_the_tool_and_one_nudge(self):
        script = [{"text": "I can't cut that from here, you'll need to do it yourself."},
                  {"text": "I still can't do that."}, {"text": "never asked"}]
        async with Harness() as h:
            calls, _, session = await _turn(h, "cut a star out of plywood with the laser", script, tool_index=True)
        self.assertEqual(len(calls), 2, "nudged once, then the reply stands")
        self.assertIn(LASER, calls[1].payload["tools"])
        self.assertIn("You were about to tell the person you cannot do this", _said(calls[1]))
        self.assertTrue(session.capability_nudged)

    @run
    async def test_saying_it_cannot_with_no_matching_tool_is_left_alone(self):
        async with Harness() as h:
            calls, _, _ = await _turn(h, "fly me to the moon", [{"text": "I can't fly you to the moon."}],
                                      tool_index=True)
        self.assertEqual(len(calls), 1)


class TheConfig(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(Config().tool_index)
        self.assertTrue(Config.from_mapping({"tool_index": True}).tool_index)


if __name__ == "__main__":
    unittest.main()
