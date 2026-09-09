"""`Assembler._memory_retrieve` (16-orchestration.md section 5):
live-caught, real use (07-post-cutover-review.md section 3.4d/3.3) --
a single oversized or many small retrieved memory records could make
the elastic "conversation" block too large for Cognition's compaction
to shrink under budget, producing a real `context_too_large` failure
even with `allow_summarize=True`. Bounding what's handed to Cognition
in the first place, distinct from `tests/simorgh/orchestration/
test_session_flows.py`'s end-to-end session-state-machine coverage."""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import Assembler, _MEMORY_BLOCK_MAX_CHARS, _MEMORY_ITEM_MAX_CHARS

from .harness import Harness, run


class TestMemoryRetrieveSizeCap(unittest.TestCase):
    @run
    async def test_a_single_oversized_item_is_truncated_not_passed_through_whole(self):
        async with Harness() as h:
            memory_bus = h.client("memory")
            huge = "x" * 50_000  # far over any reasonable single-item budget

            async def _responder(message):
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
                    "items": [{"ref": "episodic:1", "content": huge, "kind": "episodic",
                               "score": 1.0, "confidence": 1.0, "ts": 0.0}],
                    "truncated": False,
                })

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
            mem = await assembler._memory_retrieve("query", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertLess(len(mem), len(huge))
            self.assertLessEqual(len(mem), _MEMORY_ITEM_MAX_CHARS + 10)
            self.assertTrue(huge.startswith(mem.removeprefix("- ").removesuffix("…")))  # real prefix, not fabricated

    @run
    async def test_many_items_are_bounded_in_aggregate(self):
        async with Harness() as h:
            memory_bus = h.client("memory")
            # 8 items, each under the per-item cap alone, but well over the
            # aggregate cap together.
            items = [{"ref": f"episodic:{i}", "content": f"item {i}: " + "y" * 700, "kind": "episodic",
                      "score": 1.0, "confidence": 1.0, "ts": 0.0} for i in range(8)]

            async def _responder(message):
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={"items": items, "truncated": False})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t2", kind="chat", mode="execute", profile=profiles.CHAT)
            mem = await assembler._memory_retrieve("query", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertLessEqual(len(mem), _MEMORY_BLOCK_MAX_CHARS + 800)  # one item's worth of slack at the boundary
            self.assertIn("item 0:", mem)  # the strongest (highest-ranked) match is kept, not dropped

    @run
    async def test_small_items_are_untouched(self):
        async with Harness() as h:
            memory_bus = h.client("memory")

            async def _responder(message):
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
                    "items": [{"ref": "semantic:1", "content": "the sky is blue", "kind": "semantic",
                               "score": 1.0, "confidence": 1.0, "ts": 0.0}],
                    "truncated": False,
                })

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t3", kind="chat", mode="execute", profile=profiles.CHAT)
            mem = await assembler._memory_retrieve("query", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertEqual(mem, "- the sky is blue")


class TestRequestsInheritTheTaskTraceId(unittest.TestCase):
    """2026-09-08 observer finding: `Assembler._request` minted a fresh
    `trace_id` (a `Message.new` default) for every internal request, so
    each of a task's memory-retrieve/world-facet calls got its own
    1-2-event `trace:<uuid>` ledger stream instead of joining the task's
    own -- measured, 3 trivial tasks produced 74 such fragments. This is
    a partial fix (see `context.py::Assembler._request`'s docstring for
    what is still out of scope): `_memory_retrieve` and `world_facet` now
    pass `session.task_id`/a caller-given `trace_id` through so those two
    call sites' requests are traceable back to the task that made them."""

    @run
    async def test_memory_retrieve_request_carries_the_session_task_id_as_trace_id(self):
        async with Harness() as h:
            memory_bus = h.client("memory")
            seen = []

            async def _responder(message):
                seen.append(message.trace_id)
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY,
                                        payload={"items": [], "truncated": False})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="trace-t1", kind="chat", mode="execute", profile=profiles.CHAT)
            await assembler._memory_retrieve("query", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertEqual(seen, ["trace-t1"])

    @run
    async def test_world_facet_request_carries_a_given_trace_id(self):
        async with Harness() as h:
            world_bus = h.client("worldmodel")
            seen = []

            async def _responder(message):
                seen.append(message.trace_id)
                await world_bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY,
                                       payload={"ok": True, "facet": "tools", "as_of": 0.0, "tools": []})

            sub = await world_bus.subscribe(topics.WORLD_ENV_QUERY, _responder)
            assembler = Assembler(h.client("orchestration"))
            await assembler.world_facet("tools", trace_id="trace-t2")
            await sub.unsubscribe()

            self.assertEqual(seen, ["trace-t2"])

    @run
    async def test_world_facet_without_a_trace_id_still_works(self):
        """Backward compatible: `trace_id` is optional, and an omitted one
        still mints a fresh id (never breaks a caller that has none)."""
        async with Harness() as h:
            world_bus = h.client("worldmodel")

            async def _responder(message):
                await world_bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY,
                                       payload={"ok": True, "facet": "tools", "as_of": 0.0, "tools": []})

            sub = await world_bus.subscribe(topics.WORLD_ENV_QUERY, _responder)
            assembler = Assembler(h.client("orchestration"))
            reply = await assembler.world_facet("tools")
            await sub.unsubscribe()

            self.assertIsNotNone(reply)


if __name__ == "__main__":
    unittest.main()


class TestTheAssembledPrompt(unittest.TestCase):
    """Token audit, 2026-09-07. Two things the assembler was getting
    wrong, both measured against a real booted system."""

    async def _assemble(self, session, *, user_text="", answer_identity=True):
        async with Harness() as h:
            other = h.client("worldmodel")
            subs = []
            if answer_identity:
                async def _self(message):
                    await other.reply(message, type=topics.SELF_SUMMARY_REPLY,
                                      payload={"text": "SELF SUMMARY BLOCK"})

                async def _voice(message):
                    await other.reply(message, type=topics.PERSONA_VOICE_REPLY,
                                      payload={"style_block": "VOICE BLOCK", "mood_phrase": ""})

                subs.append(await other.subscribe(topics.SELF_SUMMARY, _self))
                subs.append(await other.subscribe(topics.PERSONA_VOICE, _voice))
            blocks = await Assembler(h.client("orchestration")).assemble(
                session, session.profile.scaffold, user_text=user_text,
            )
            for sub in subs:
                await sub.unsubscribe()
            return blocks

    @run
    async def test_the_voice_and_self_summary_are_not_fetched_here(self):
        """Cognition's own assembler owns both as protected blocks (04
        section 5). Fetching them here too put a verbatim second copy in
        every prompt -- 198 of 819 measured tokens -- and cost two extra
        bus round trips per think call."""
        session = Session(task_id="t1", kind="patch", mode="execute",
                          profile=profiles.PATCH, user_text="add a docstring")
        blocks = await self._assemble(session)
        text = " ".join(b["content"] for b in blocks)
        self.assertNotIn("SELF SUMMARY BLOCK", text)
        self.assertNotIn("VOICE BLOCK", text)

    @run
    async def test_the_task_is_present_on_a_later_step_not_only_the_first(self):
        """`session.py` clears `pending_user_text` after one use, and the
        request never entered `session.messages` -- so from step 2 of 8 a
        patch session no longer had the instruction in front of it, only
        its own tool output. A run that applied a file and then stopped
        had genuinely lost the task by then."""
        session = Session(task_id="t1", kind="patch", mode="execute",
                          profile=profiles.PATCH, user_text="add a docstring to the retry helper")
        session.messages.append({"role": "assistant", "content": "[tool_call read_file] -> ..."})
        blocks = await self._assemble(session, user_text="")  # a later step passes none
        self.assertIn("add a docstring to the retry helper",
                      " ".join(b["content"] for b in blocks))

    @run
    async def test_the_task_comes_before_the_transcript(self):
        session = Session(task_id="t1", kind="patch", mode="execute",
                          profile=profiles.PATCH, user_text="the task")
        session.messages.append({"role": "assistant", "content": "a step"})
        blocks = await self._assemble(session)
        contents = [b["content"] for b in blocks]
        self.assertLess(contents.index("the task"), contents.index("a step"))

    @run
    async def test_a_session_with_no_task_text_still_assembles(self):
        session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
        blocks = await self._assemble(session)
        self.assertEqual(blocks, [])


if __name__ == "__main__":
    unittest.main()
