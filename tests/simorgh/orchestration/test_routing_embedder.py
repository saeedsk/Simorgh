"""Tool routing with Memory's embedder (stage 17, `memory.embed`): the
groups' utterances are embedded once, each routed turn within
`route_embed_timeout_s`; a turn Memory does not answer in time (or
refuses) is routed with the lexical stand-in and says so. Off sends
nothing at all."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.orchestration import profiles, routing
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner
from simorgh.orchestration.tools import offered_tools

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run

GROUPS = routing.load_groups()
NAMES = [g.name for g in GROUPS]
#: A turn the fake model places in `cameras`, where the lexical stand-in
#: never would: proof the route came from Memory's vectors.
ODD = "it is far too gloomy in here"
TARGET = "cameras"


def _onehot(i: int) -> list[float]:
    vec = [0.0] * len(NAMES)
    vec[i] = 1.0
    return vec


class FakeMemory:
    """Answers `memory.embed` like a semantic model would, in miniature:
    each utterance to its own group's axis, anything else to `TARGET`'s.
    `turn_delay` holds back the answer to a one-text request (a turn)."""

    def __init__(self, bus, *, turn_delay: float = 0.0, refuse: str = "", turn_model: str = "fake") -> None:
        self._bus = bus
        self.turn_delay = turn_delay
        self.refuse = refuse
        #: The model a one-text request (a turn) is answered with: another
        #: than the table's is Memory's embedder changing under the router.
        self.turn_model = turn_model
        self.requests: list[list[str]] = []
        self._axis = {u: NAMES.index(g.name) for g in GROUPS for u in g.utterances}

    async def start(self):
        self._sub = await self._bus.subscribe(topics.MEMORY_EMBED, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        texts = list((message.payload or {}).get("texts") or [])
        self.requests.append(texts)
        if self.refuse:
            payload = {"vectors": [], "model": "hashing", "dimension": 256, "refused": self.refuse}
        else:
            if len(texts) == 1 and self.turn_delay:
                await asyncio.sleep(self.turn_delay)
            other = NAMES.index(TARGET)
            model = self.turn_model if len(texts) == 1 else "fake"
            payload = {"vectors": [_onehot(self._axis.get(t, other)) for t in texts],
                       "model": model, "dimension": len(NAMES)}
        await self._bus.reply(message, type=topics.MEMORY_EMBED_REPLY, payload=payload)


async def _turn(h, memory, text, *, warm=True, settle=False, **runner_kw):
    cognition = FakeCognition(h.client("cognition"), script=[{"text": "sure"}])
    gx = FakeGuardianExecution(h.client("guardian"))
    await cognition.start(); await gx.start(); await memory.start()
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0,
                           assemble_timeout_s=0.05, **runner_kw)
    if warm:
        runner.warm_routing()
        if runner._route_warming is not None:  # noqa: SLF001
            await asyncio.wait_for(runner._route_warming, timeout=5)  # noqa: SLF001
    session = Session(task_id="t0", kind="chat", mode="execute", profile=profiles.CHAT, user_text=text)
    await asyncio.wait_for(runner.run(session, user_text=text), timeout=10)
    if settle and runner._route_warming is not None:  # noqa: SLF001 -- a fetch the turn started
        await asyncio.wait_for(runner._route_warming, timeout=5)  # noqa: SLF001
    await runner.stop_routing()
    await cognition.stop(); await gx.stop(); await memory.stop()
    return cognition.calls, session, runner


class MemorysEmbedderRoutes(unittest.TestCase):
    @run
    async def test_a_turn_is_routed_by_memorys_vectors(self):
        async with Harness() as h:
            memory = FakeMemory(h.client("memory"))
            calls, session, runner = await _turn(h, memory, ODD, tool_routing="on")
        self.assertEqual(session.route_embedder, f"memory:fake/{len(NAMES)}")
        self.assertEqual(session.route_fallback, "")
        self.assertIn(TARGET, session.route)
        self.assertIn("camera_describe", calls[0].payload["tools"])
        # The utterances once, in one request, then the turn alone.
        self.assertEqual(len(memory.requests), 2)
        self.assertEqual(memory.requests[0], list(routing.utterances(GROUPS)))
        self.assertEqual(memory.requests[1], [ODD])
        self.assertEqual(list(runner._route_tables), [("fake", len(NAMES))])  # noqa: SLF001
        # The lexical stand-in alone could not have placed it.
        self.assertNotIn(TARGET, routing.route(ODD, (), GROUPS, aggregate="nearest"))

    @run
    async def test_shadow_records_the_embedder(self):
        events = []

        class _Telemetry:
            def event(self, name, **kw):
                events.append((name, kw.get("attrs") or {}))

        async with Harness() as h:
            memory = FakeMemory(h.client("memory"))
            await _turn(h, memory, ODD, tool_routing="shadow", telemetry=_Telemetry())
        shadow = next(a for n, a in events if n == "routing.shadow")
        self.assertEqual(shadow["embedder"], f"memory:fake/{len(NAMES)}")
        self.assertEqual(shadow["fallback"], "")


    @run
    async def test_a_table_past_the_request_bound_is_asked_for_in_chunks(self):
        from unittest import mock

        from simorgh.orchestration import session as session_mod

        async with Harness() as h:
            memory = FakeMemory(h.client("memory"))
            with mock.patch.object(session_mod, "EMBED_MAX_TEXTS", 50):
                _, session, runner = await _turn(h, memory, ODD, tool_routing="on")
        wanted = list(routing.utterances(GROUPS))
        table_requests = memory.requests[:-1]
        self.assertGreater(len(table_requests), 1)
        self.assertTrue(all(len(r) <= 50 for r in table_requests))
        self.assertEqual([t for r in table_requests for t in r], wanted)
        self.assertEqual(session.route_embedder, f"memory:fake/{len(NAMES)}")
        self.assertIn(TARGET, session.route)


class TheFallback(unittest.TestCase):
    @run
    async def test_a_turn_not_answered_in_time_is_routed_lexically_and_says_so(self):
        async with Harness() as h:
            memory = FakeMemory(h.client("memory"), turn_delay=1.0)
            calls, session, _ = await _turn(h, memory, "turn the kitchen light off", tool_routing="on",
                                            route_embed_timeout_s=0.05)
        self.assertEqual(session.route_embedder, "lexical")
        self.assertIn("no answer within 0.05s", session.route_fallback)
        self.assertIn("home", session.route, "the lexical stand-in still routes it")
        self.assertIn("camera_describe", calls[0].payload["tools"])

    @run
    async def test_a_refusal_is_lexical_and_not_asked_again_at_once(self):
        async with Harness() as h:
            memory = FakeMemory(h.client("memory"), refuse="the embedder is hashing")
            _, session, runner = await _turn(h, memory, "turn the kitchen light off", tool_routing="on")
            self.assertEqual(session.route_embedder, "lexical")
            self.assertIn("the embedder is hashing", session.route_fallback)
            self.assertEqual(len(memory.requests), 1, "the table was asked for once; no turn request without it")
            runner.warm_routing()
            self.assertTrue(runner._route_warming is None or runner._route_warming.done(),  # noqa: SLF001
                            "backing off after a refusal")

    @run
    async def test_a_turn_from_another_model_is_lexical_and_the_table_is_fetched_again(self):
        async with Harness() as h:
            memory = FakeMemory(h.client("memory"), turn_model="other")
            _, session, runner = await _turn(h, memory, "turn the kitchen light off", settle=True,
                                             tool_routing="on")
        self.assertEqual(session.route_embedder, "lexical")
        self.assertIn("came back other/", session.route_fallback)
        # The table was asked for again at once (no back-off): twice in all.
        self.assertEqual(sum(len(r) > 1 for r in memory.requests), 2)
        self.assertEqual(runner._route_retry_at, 0.0)  # noqa: SLF001

    @run
    async def test_no_table_yet_is_lexical(self):
        async with Harness() as h:
            memory = FakeMemory(h.client("memory"), turn_delay=0.0)
            _, session, _ = await _turn(h, memory, "turn the kitchen light off", warm=False, tool_routing="on")
        self.assertEqual(session.route_embedder, "lexical")
        self.assertIn("no utterance vectors yet", session.route_fallback)


class OffAsksNothing(unittest.TestCase):
    @run
    async def test_off_sends_no_embed_request_and_the_same_tools(self):
        async with Harness() as h:
            memory = FakeMemory(h.client("memory"))
            calls, session, _ = await _turn(h, memory, ODD)
        self.assertEqual(memory.requests, [])
        self.assertIsNone(session.route)
        self.assertEqual(session.route_embedder, "")
        self.assertEqual(calls[0].payload["tools"], list(offered_tools(profiles.CHAT.tools)))

    @run
    async def test_an_injected_embedder_never_asks_memory(self):
        async with Harness() as h:
            memory = FakeMemory(h.client("memory"))
            _, session, _ = await _turn(h, memory, "turn the kitchen light off", tool_routing="on",
                                        route_embed=routing.lexical_embed)
        self.assertEqual(memory.requests, [])
        self.assertEqual(session.route_embedder, "lexical")


class TheTimeoutKey(unittest.TestCase):
    def test_default_problems_and_floor(self):
        from simorgh.orchestration.config import Config

        self.assertEqual(Config.from_mapping({}).route_embed_timeout_s, 0.3)
        bad = Config.from_mapping({"route_embed_timeout_s": "slow"})
        self.assertEqual(bad.route_embed_timeout_s, 0.3)
        self.assertTrue(any("route_embed_timeout_s" in p for p in bad.problems))
        self.assertEqual(Config.from_mapping({"route_embed_timeout_s": -1}).route_embed_timeout_s, 0.0)
        self.assertEqual(Config.from_mapping({"route_embed_timeout_s": "0.5"}).route_embed_timeout_s, 0.5)


class TheVectorsTable(unittest.TestCase):
    def test_turns_share_one_cached_centroid_set(self):
        table = routing.Vectors("m", 2, {"a": (1.0, 0.0)})
        one, two = table.with_text("x", (1.0, 0.0)), table.with_text("y", (0.0, 1.0))
        self.assertEqual(one, two)
        self.assertEqual(hash(one), hash(two))
        self.assertEqual(one("x"), (1.0, 0.0))
        self.assertEqual(two("y"), (0.0, 1.0))
        self.assertNotEqual(table, routing.Vectors("m", 2, {"a": (1.0, 0.0)}), "another fetch, another table")
        with self.assertRaises(KeyError):
            one("unseen")


if __name__ == "__main__":
    unittest.main()
