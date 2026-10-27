"""Tool routing (stage 17 items 3 and 6, `routing.py`; docs/plan/
stage-17-tool-routing-and-prompt-compression.md): which tool groups a
chat turn is offered, and the plan's acceptance tests -- routing,
stickiness, a stable order, `tool_more` adding a group, the
conversational route, and `off` changing nothing at all."""

from __future__ import annotations

import asyncio
import fnmatch
import re
import unittest

from simorgh.orchestration import profiles, routing
from simorgh.orchestration.api import Session
from simorgh.orchestration.config import ABLATABLE, Config
from simorgh.orchestration.session import SessionRunner
from simorgh.orchestration.tools import _TOOL_POLICY, is_read_only, offered_tools

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run

GROUPS = routing.load_groups()
_FARSI = re.compile(r"[؀-ۿ]")


def _route(text, history=(), **kw):
    return routing.route(text, history, GROUPS, aggregate="nearest", **kw)


class _Telemetry:
    def __init__(self):
        self.events = []

    def event(self, name, **kw):
        self.events.append((name, kw.get("attrs") or {}))


def _expand(names):
    """A profile's tools with patterns expanded the way `profiles.py` and
    `offered_tools` do before anything has registered: against the policy table."""
    out = []
    for name in names:
        if any(c in name for c in "*?["):
            out.extend(sorted(t for t in _TOOL_POLICY if fnmatch.fnmatchcase(t, name)))
        else:
            out.append(name)
    return out


class TheGroupsFile(unittest.TestCase):
    def test_every_chat_and_voice_tool_is_in_exactly_one_group(self):
        for profile in (profiles.CHAT, profiles.VOICE_CHAT):
            for tool in _expand(profile.tools):
                homes = [g.name for g in GROUPS if any(fnmatch.fnmatchcase(tool, p) for p in g.tools)]
                self.assertEqual(len(homes), 1, f"{tool} ({profile.name}) is in {homes or 'no group'}")

    def test_each_group_says_what_it_is_in_both_languages(self):
        for group in GROUPS:
            self.assertTrue(group.description, group.name)
            farsi = [u for u in group.utterances if _FARSI.search(u)]
            english = [u for u in group.utterances if not _FARSI.search(u)]
            self.assertTrue(5 <= len(english) <= 15, f"{group.name}: {len(english)} English utterances")
            self.assertTrue(5 <= len(farsi) <= 15, f"{group.name}: {len(farsi)} Farsi utterances")

    def test_the_core_group_is_memory_with_tool_more(self):
        core = [g for g in GROUPS if g.core]
        self.assertEqual([g.name for g in core], ["memory"])
        self.assertTrue({"remember", "memory_search", "memory_forget", "tool_more"} <= set(core[0].tools))

    def test_the_conversational_class_has_no_tools(self):
        conv = next(g for g in GROUPS if g.name == routing.CONVERSATIONAL)
        self.assertEqual(conv.tools, ())

    def test_canonical_order_is_by_name(self):
        self.assertEqual([g.name for g in GROUPS], sorted(g.name for g in GROUPS))

    def test_an_unknown_key_is_refused(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.toml"
            path.write_text('[groups.x]\ndescription = "x"\ntools = []\nutterance = ["typo"]\n')
            with self.assertRaises(routing.GroupsFileError):
                routing.load_groups(path)


class Routing(unittest.TestCase):
    def test_a_light_goes_to_home_and_the_core_rides_along(self):
        for text in ("turn the kitchen light off", "چراغ آشپزخانه را خاموش کن"):
            got = _route(text)
            self.assertIn("home", got, text)
            self.assertIn("memory", got, text)

    def test_other_requests_find_their_group(self):
        cases = {"play some jazz in the kitchen": "media", "what's on my calendar tomorrow": "calendar_mail",
                 "what does the front door camera see": "cameras", "what's the weather tomorrow": "web",
                 "یک آهنگ جاز پخش کن": "media", "فردا تقویمم چی داره": "calendar_mail"}
        for text, group in cases.items():
            self.assertIn(group, _route(text), text)

    def test_at_most_top_k_groups_beside_the_core(self):
        got = _route("turn the kitchen light off", top_k=2)
        self.assertLessEqual(len(set(got) - {"memory"}), 2)

    def test_sorted_by_name(self):
        got = _route("play some jazz in the kitchen")
        self.assertEqual(list(got), sorted(got))

    def test_no_evidence_narrows_nothing(self):
        got = _route("")
        self.assertEqual(set(got), {g.name for g in GROUPS if g.name != routing.CONVERSATIONAL})

    def test_centroid_is_the_default_aggregate(self):
        """The plan's: cosine to the utterance centroid. `nearest` is the
        lexical stand-in's (see `routing.AGGREGATES`)."""
        scored = routing.scores("turn the kitchen light off", GROUPS)
        self.assertEqual(max(scored, key=scored.get), "home")


class Stickiness(unittest.TestCase):
    def test_a_group_used_lately_stays_offered(self):
        got = _route("and the bedroom one?", history=[("media",)])
        self.assertIn("media", got)

    def test_it_lasts_route_sticky_turns_turns(self):
        history = [("security",), (), (), ()]
        self.assertNotIn("security", _route("turn the kitchen light off", history=history, sticky_turns=3))
        self.assertIn("security", _route("turn the kitchen light off", history=history, sticky_turns=4))

    def test_zero_is_off(self):
        self.assertNotIn("security", _route("turn the kitchen light off", history=[("security",)], sticky_turns=0))


class TheConversationalRoute(unittest.TestCase):
    """Item 6, the bouncer: a turn that needs no tool is offered the core
    group only. Not a model call -- the router's own class."""

    def test_thanks_and_greetings_get_only_the_core(self):
        for text in ("thanks!", "hello", "say that again please", "مرسی", "سلام سیم", "منظورت چی بود"):
            self.assertEqual(_route(text), ("memory",), text)

    def test_it_must_win_by_the_margin(self):
        self.assertNotEqual(_route("hello", none_margin=0.99), ("memory",))

    def test_a_request_is_not_conversational(self):
        self.assertNotEqual(_route("turn the kitchen light off"), ("memory",))

    def test_sticky_groups_do_not_survive_a_thanks(self):
        self.assertEqual(_route("thanks!", history=[("home",)]), ("memory",))


class StableOrder(unittest.TestCase):
    def test_the_same_groups_in_any_order_give_the_same_tools(self):
        offered = offered_tools(profiles.CHAT.tools) + (routing.TOOL_MORE,)
        a = routing.tools_for(("web", "home", "memory"), GROUPS, offered)
        b = routing.tools_for(("memory", "web", "home"), GROUPS, tuple(reversed(offered)))
        self.assertEqual(a, b)
        home_at = a.index("home_find")
        memory_at = a.index("remember")
        web_at = a.index("web_search")
        self.assertLess(home_at, memory_at)
        self.assertLess(memory_at, web_at)

    def test_a_tool_in_no_group_is_never_hidden(self):
        got = routing.tools_for(("home",), GROUPS, ("home_state", "skill:greet", "web_search"))
        self.assertEqual(got, ("home_state", "skill:greet"))


class TheConfig(unittest.TestCase):
    def test_off_by_default(self):
        cfg = Config()
        self.assertEqual((cfg.tool_routing, cfg.route_top_k, cfg.route_sticky_turns, cfg.route_none_margin),
                         ("off", 3, 3, 0.15))

    def test_an_unknown_mode_is_a_problem_and_off(self):
        cfg = Config.from_mapping({"tool_routing": "sometimes"})
        self.assertEqual(cfg.tool_routing, "off")
        self.assertIn("tool_routing", cfg.problems[0])

    def test_known_modes_pass(self):
        for mode in ("off", "shadow", "on", "ON"):
            cfg = Config.from_mapping({"tool_routing": mode})
            self.assertEqual(cfg.tool_routing, mode.lower())
            self.assertEqual(cfg.problems, ())

    def test_bad_numbers_are_problems(self):
        cfg = Config.from_mapping({"route_top_k": "three", "route_none_margin": "wide"})
        self.assertEqual(cfg.route_top_k, 3)
        self.assertEqual(cfg.route_none_margin, 0.15)
        self.assertEqual(len(cfg.problems), 2)

    def test_routing_can_be_ablated(self):
        self.assertIn("routing", ABLATABLE)

    def test_tool_more_is_read_only_to_the_router(self):
        self.assertTrue(is_read_only("tool_more"))


async def _turns(h, texts, *, script=None, telemetry=None, execution=True, speaker="", **runner_kw):
    """Run one chat turn per text through a real SessionRunner; the
    `cognition.think` payloads come back, with the proposals Guardian saw."""
    cognition = FakeCognition(h.client("cognition"), script=list(script or [{"text": "sure"}]))
    gx = FakeGuardianExecution(h.client("guardian")) if execution else None
    await cognition.start()
    if gx is not None:
        await gx.start()
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0,
                           assemble_timeout_s=0.05, telemetry=telemetry, **runner_kw)
    sessions = []
    for i, words in enumerate(texts):
        session = Session(task_id=f"t{i}", kind="chat", mode="execute", profile=profiles.CHAT,
                          user_text=words, speaker=speaker)
        sessions.append(session)
        await asyncio.wait_for(runner.run(session, user_text=words), timeout=10)
    await cognition.stop()
    if gx is not None:
        await gx.stop()
    return cognition.calls, (gx.proposals if gx else []), sessions


def _same(a, b):
    return {k: a[k] for k in ("tools", "task_rules", "messages")} == {k: b[k] for k in ("tools", "task_rules", "messages")}


class OffChangesNothing(unittest.TestCase):
    @run
    async def test_off_and_shadow_send_the_prompt_of_a_runner_without_routing(self):
        sent = {}
        for mode in (None, "off", "shadow"):
            async with Harness() as h:
                kw = {} if mode is None else {"tool_routing": mode}
                calls, _, _ = await _turns(h, ["turn the kitchen light off"], **kw)
            sent[mode] = calls[0].payload
        self.assertTrue(_same(sent[None], sent["off"]))
        self.assertTrue(_same(sent[None], sent["shadow"]), "shadow still offers everything")
        self.assertEqual(sent["off"]["tools"], list(offered_tools(profiles.CHAT.tools)))
        self.assertNotIn("tool_more", sent["off"]["tools"])

    @run
    async def test_ablate_routing_is_off(self):
        async with Harness() as h:
            calls, _, _ = await _turns(h, ["thanks!"], tool_routing="on", ablate=("routing",))
        self.assertEqual(calls[0].payload["tools"], list(offered_tools(profiles.CHAT.tools)))


class OnOffersTheRoute(unittest.TestCase):
    @run
    async def test_a_turn_is_offered_its_groups_and_the_core(self):
        async with Harness() as h:
            calls, _, sessions = await _turns(h, ["turn the kitchen light off"], tool_routing="on")
        tools = calls[0].payload["tools"]
        self.assertIn("home_call", tools)
        self.assertIn("remember", tools)
        self.assertIn("tool_more", tools)
        self.assertNotIn("sec_posture", tools)
        self.assertLess(len(tools), len(offered_tools(profiles.CHAT.tools)))
        self.assertEqual(tools, list(routing.tools_for(sessions[0].route, GROUPS,
                                                       offered_tools(profiles.CHAT.tools) + ("tool_more",))))

    @run
    async def test_two_turns_routed_alike_send_a_byte_identical_tool_block(self):
        async with Harness() as h:
            calls, _, sessions = await _turns(h, ["turn the kitchen light off", "turn the kitchen light on"],
                                              tool_routing="on")
        self.assertEqual(sessions[0].route, sessions[1].route)
        first, second = (c.payload for c in calls[:2])
        self.assertEqual(first["tools"], second["tools"])
        self.assertEqual(first["task_rules"], second["task_rules"])

    @run
    async def test_a_thanks_is_offered_the_core_only(self):
        async with Harness() as h:
            calls, _, sessions = await _turns(h, ["thanks!"], tool_routing="on")
        self.assertTrue(sessions[0].route_conversational)
        self.assertEqual(set(calls[0].payload["tools"]), {"remember", "memory_search", "memory_forget", "tool_more"})


class ToolMore(unittest.TestCase):
    @run
    async def test_it_goes_to_guardian_and_adds_the_group_to_the_next_step(self):
        script = [{"tool_calls": [{"tool": "tool_more", "args": {"group": "security"}}]}, {"text": "done"}]
        async with Harness() as h:
            calls, proposals, sessions = await _turns(h, ["turn the kitchen light off"], script=script,
                                                      tool_routing="on")
        self.assertNotIn("sec_posture", calls[0].payload["tools"])
        self.assertIn("sec_posture", calls[1].payload["tools"])
        self.assertEqual([p.payload["tool"] for p in proposals], ["tool_more"])
        self.assertEqual(proposals[0].payload["args"], {"group": "security"})
        self.assertEqual(proposals[0].payload["reversibility"], "read_only")
        self.assertEqual(sessions[0].route_more, ["security"])

    @run
    async def test_a_marker_argument_is_the_group(self):
        script = [{"tool_calls": [{"tool": "tool_more", "args": {"argument": "Security"}}]}, {"text": "done"}]
        async with Harness() as h:
            calls, proposals, _ = await _turns(h, ["turn the kitchen light off"], script=script, tool_routing="on")
        self.assertEqual(proposals[0].payload["args"], {"group": "security"})
        self.assertIn("sec_posture", calls[1].payload["tools"])

    @run
    async def test_an_unknown_group_is_refused_with_the_list_and_never_proposed(self):
        script = [{"tool_calls": [{"tool": "tool_more", "args": {"group": "lasers"}}]}, {"text": "done"}]
        async with Harness() as h:
            calls, proposals, sessions = await _turns(h, ["turn the kitchen light off"], script=script,
                                                      tool_routing="on")
        self.assertEqual(proposals, [])
        self.assertEqual(sessions[0].route_more, [])
        said = " ".join(str(m.get("content")) for m in calls[1].payload["messages"])
        self.assertIn("no group called 'lasers'", said)
        self.assertIn("security", said)

    @run
    async def test_a_denied_tool_more_adds_nothing(self):
        script = [{"tool_calls": [{"tool": "tool_more", "args": {"group": "security"}}]}, {"text": "done"}]
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=script)
            gx = FakeGuardianExecution(h.client("guardian"), deny=True)
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0,
                                   assemble_timeout_s=0.05, tool_routing="on")
            session = Session(task_id="t-deny", kind="chat", mode="execute", profile=profiles.CHAT,
                              user_text="turn the kitchen light off")
            await asyncio.wait_for(runner.run(session, user_text=session.user_text), timeout=10)
            await cognition.stop(); await gx.stop()
        self.assertEqual(session.route_more, [])
        self.assertNotIn("sec_posture", cognition.calls[1].payload["tools"])

    @run
    async def test_a_tool_not_shown_is_still_callable_and_its_group_follows(self):
        """A tool not offered is not a tool denied: the model calls one it
        knows from an earlier turn, Guardian decides, and its group is
        offered from the next step."""
        script = [{"tool_calls": [{"tool": "sec_posture", "args": {}}]}, {"text": "done"}]
        async with Harness() as h:
            calls, proposals, sessions = await _turns(h, ["turn the kitchen light off"], script=script,
                                                      tool_routing="on")
        self.assertEqual([p.payload["tool"] for p in proposals], ["sec_posture"])
        self.assertIn("security", sessions[0].route_more)
        self.assertIn("sec_posture", calls[1].payload["tools"])


class ABrokenRouterNeverCostsATurn(unittest.TestCase):
    """Routing decides what is offered; when it cannot decide, the turn is
    offered everything, as with routing off -- never a crashed turn."""

    @run
    async def test_an_unreadable_groups_file_offers_everything(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        telemetry = _Telemetry()
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "groups.toml"
            bad.write_text("[groups.x\n")
            for mode in ("shadow", "on"):
                with mock.patch.object(routing, "GROUPS_FILE", bad), \
                        mock.patch.object(routing.load_groups, "__defaults__", (bad,)):
                    async with Harness() as h:
                        calls, _, sessions = await _turns(h, ["turn the kitchen light off"],
                                                          telemetry=telemetry, tool_routing=mode)
                self.assertEqual(calls[0].payload["tools"], list(offered_tools(profiles.CHAT.tools)), mode)
                self.assertIsNone(sessions[0].route, mode)
        self.assertIn("routing.failed", [n for n, _ in telemetry.events])

    @run
    async def test_an_embedder_that_raises_offers_everything(self):
        def broken(text):
            raise RuntimeError("no embedder")

        telemetry = _Telemetry()
        async with Harness() as h:
            calls, _, sessions = await _turns(h, ["turn the kitchen light off"], telemetry=telemetry,
                                              tool_routing="on", route_embed=broken)
        self.assertEqual(calls[0].payload["tools"], list(offered_tools(profiles.CHAT.tools)))
        self.assertIsNone(sessions[0].route)
        self.assertEqual([n for n, _ in telemetry.events if n.startswith("routing.")], ["routing.failed"])


class ShadowRecordsTheRoute(unittest.TestCase):
    @run
    async def test_each_turn_logs_offered_and_used_and_the_next_turn_sticks(self):
        telemetry = _Telemetry()
        script = [{"tool_calls": [{"tool": "sec_posture", "args": {}}]}, {"text": "done"}]
        async with Harness() as h:
            calls, _, sessions = await _turns(h, ["turn the kitchen light off", "and the porch light?"],
                                              script=script, telemetry=telemetry, tool_routing="shadow")
        names = [n for n, _ in telemetry.events if n.startswith("routing.")]
        self.assertEqual(names, ["routing.shadow", "routing.shadow"])
        first = next(a for n, a in telemetry.events if n == "routing.shadow")
        self.assertIn("home", first["offered"])
        self.assertEqual(first["used"], ["sec_posture"])
        self.assertEqual(first["missed"], ["sec_posture"], "the router would not have offered it")
        self.assertFalse(first["conversational"])
        # Shadow offered everything, both turns.
        self.assertEqual(calls[0].payload["tools"], list(offered_tools(profiles.CHAT.tools)))
        # The second turn keeps the group the first one used.
        self.assertIn("security", sessions[1].route)

    @run
    async def test_stickiness_is_per_conversation(self):
        script = [{"tool_calls": [{"tool": "sec_posture", "args": {}}]}, {"text": "done"}]
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=script)
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0,
                                   assemble_timeout_s=0.05, tool_routing="shadow")
            first = Session(task_id="a", kind="chat", mode="execute", profile=profiles.CHAT,
                            user_text="turn the kitchen light off", channel="voice", speaker="Saeed")
            await asyncio.wait_for(runner.run(first, user_text=first.user_text), timeout=10)
            other = Session(task_id="b", kind="chat", mode="execute", profile=profiles.CHAT,
                            user_text="turn the kitchen light off", channel="voice", speaker="Soodeh")
            await asyncio.wait_for(runner.run(other, user_text=other.user_text), timeout=10)
            await cognition.stop(); await gx.stop()
        self.assertNotIn("security", other.route)

    def test_only_the_persons_own_chat_turn_is_routed(self):
        from dataclasses import replace

        runner = SessionRunner(None, None, tool_routing="on")
        chat = Session(task_id="c", kind="chat", mode="execute", profile=profiles.CHAT)
        voice = Session(task_id="v", kind="chat", mode="execute", profile=profiles.VOICE_CHAT, channel="voice")
        task = Session(task_id="r", kind="research", mode="execute", profile=profiles.RESEARCH)
        helper = replace(chat, task_id="h", depth=1)
        member = replace(chat, task_id="m", crew_member=True)
        self.assertEqual([runner._routes(s) for s in (chat, voice, task, helper, member)],  # noqa: SLF001
                         [True, True, False, False, False])
        self.assertFalse(SessionRunner(None, None)._routes(chat))  # noqa: SLF001 -- off by default


if __name__ == "__main__":
    unittest.main()
