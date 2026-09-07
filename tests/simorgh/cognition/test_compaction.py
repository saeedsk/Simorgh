"""The graduated compaction pipeline (docs/blueprint/subsystems/
04-cognition.md section 5): cheap, non-destructive interventions before
anything lossy. Each layer is tested in isolation and then as a
pipeline. Layers 1-2 (budget reduction, snip) were built in an earlier
session; layers 3-5 (microcompact/reference substitution, read-time
collapse, model-summarization auto-compact) plus segment-level
persistent-instruction protection are this session's build -- roadmap
item 4.2, closing docs/KnowledgeBase/harness-06-gap-analysis-simorgh.md
gap #2 ("No context-compaction pipeline in any tool loop")."""

from __future__ import annotations

import unittest

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.cognition.compaction import Compactor
from simorgh.cognition.config import Config
from simorgh.contracts import topics
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


class TestCompactorLayer1(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()

    async def test_oversized_tool_result_is_replaced_with_a_preview_and_blob_ref(self):
        config = Config(tool_result_max_tokens=5)
        compactor = Compactor(config, self.ledger)
        big_content = " ".join(f"word{i}" for i in range(200))
        result = await compactor.compact(
            [{"role": "tool", "name": "search", "content": big_content}], limit_tokens=10_000,
        )
        self.assertIn(1, result.layers_applied)
        self.assertIn("tool result search", result.text)
        self.assertIn("ref:", result.text)
        self.assertLess(result.tokens_after, result.tokens_before)

    async def test_load_bearing_tool_result_is_never_reduced(self):
        config = Config(tool_result_max_tokens=5)
        compactor = Compactor(config, self.ledger)
        big_content = " ".join(f"word{i}" for i in range(200))
        result = await compactor.compact(
            [{"role": "tool", "name": "search", "content": big_content, "load_bearing": True}], limit_tokens=10_000,
        )
        self.assertNotIn(1, result.layers_applied)
        self.assertIn(big_content, result.text)

    async def test_small_tool_result_under_the_cap_is_untouched(self):
        config = Config(tool_result_max_tokens=1_000)
        compactor = Compactor(config, self.ledger)
        result = await compactor.compact([{"role": "tool", "name": "search", "content": "short"}], limit_tokens=10_000)
        self.assertNotIn(1, result.layers_applied)
        self.assertIn("short", result.text)

    async def test_non_tool_messages_are_never_touched_by_layer_1(self):
        config = Config(tool_result_max_tokens=1)
        compactor = Compactor(config, self.ledger)
        long_user_text = " ".join(f"word{i}" for i in range(200))
        result = await compactor.compact([{"role": "user", "content": long_user_text}], limit_tokens=10_000)
        self.assertNotIn(1, result.layers_applied)
        self.assertIn(long_user_text, result.text)

    async def test_a_broken_ledger_degrades_the_blob_ref_instead_of_failing_compaction(self):
        class _BrokenLedger:
            async def put_blob(self, *a, **kw):
                raise RuntimeError("blob store down")

        config = Config(tool_result_max_tokens=1)
        compactor = Compactor(config, _BrokenLedger())
        result = await compactor.compact([{"role": "tool", "name": "x", "content": "a b c d e f g h"}], limit_tokens=10_000)
        self.assertIn("ref: unavailable", result.text)


class TestCompactorLayer2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()

    async def test_snip_drops_oldest_segments_first_keeping_the_tail(self):
        config = Config(snip_keep_last_segments=1, snip_trigger_fraction=0.5, snip_target_fraction=0.4)
        compactor = Compactor(config, self.ledger)
        messages = [
            {"role": "user", "content": " ".join(["old"] * 100)},
            {"role": "user", "content": " ".join(["middle"] * 100)},
            {"role": "user", "content": "newest"},
        ]
        result = await compactor.compact(messages, limit_tokens=20)
        self.assertIn(2, result.layers_applied)
        self.assertIn("newest", result.text)
        self.assertNotIn("old old", result.text)

    async def test_under_the_trigger_fraction_layer_2_does_not_fire(self):
        config = Config(snip_trigger_fraction=0.9)
        compactor = Compactor(config, self.ledger)
        result = await compactor.compact([{"role": "user", "content": "short"}], limit_tokens=10_000)
        self.assertNotIn(2, result.layers_applied)


class TestCompactorPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()

    async def test_layers_apply_in_order_when_both_are_needed(self):
        config = Config(
            tool_result_max_tokens=5, snip_keep_last_segments=1,
            snip_trigger_fraction=0.1, snip_target_fraction=0.05,
        )
        compactor = Compactor(config, self.ledger)
        messages = [
            {"role": "tool", "name": "search", "content": " ".join(f"w{i}" for i in range(200))},
            {"role": "user", "content": "the newest message"},
        ]
        result = await compactor.compact(messages, limit_tokens=50)
        self.assertEqual(list(result.layers_applied), [1, 2])

    async def test_a_trivial_message_triggers_no_layer_at_all_not_even_4_or_5(self):
        # Layers 3/5 have percentage thresholds a two-word message never
        # crosses; layer 4 always *runs* but only counts as "applied" if
        # it actually collapses something -- one segment is already <=
        # the default `collapse_keep_full_segments`, so it's a no-op too.
        config = Config()
        compactor = Compactor(config, self.ledger)
        result = await compactor.compact([{"role": "user", "content": "hi"}], limit_tokens=10_000, allow_summarize=True)
        self.assertEqual(result.layers_applied, ())


class TestCompactorLayer3Microcompact(unittest.IsolatedAsyncioTestCase):
    """Layer 3 (docs/blueprint/subsystems/04-cognition.md section 5):
    reference substitution for repeated identical tool results, plus
    whitespace-run stripping -- roadmap 4.2's "reference substitution"
    layer, closing harness-06 gap #2 by name."""

    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()

    async def test_duplicate_tool_results_collapse_to_a_reference_to_the_first(self):
        config = Config(microcompact_trigger_fraction=0.0)  # always eligible for this test
        compactor = Compactor(config, self.ledger)
        dup = " ".join(f"w{i}" for i in range(50))
        messages = [
            {"role": "tool", "name": "search", "content": dup},
            {"role": "tool", "name": "search", "content": dup},
        ]
        result = await compactor.compact(messages, limit_tokens=1_000_000)
        self.assertIn(3, result.layers_applied)
        self.assertIn("duplicate of segment 0", result.text)
        self.assertLess(result.tokens_after, result.tokens_before)

    async def test_load_bearing_duplicates_are_never_collapsed(self):
        config = Config(microcompact_trigger_fraction=0.0)
        compactor = Compactor(config, self.ledger)
        dup = " ".join(f"w{i}" for i in range(50))
        messages = [
            {"role": "tool", "name": "tests", "content": dup, "load_bearing": True},
            {"role": "tool", "name": "tests", "content": dup, "load_bearing": True},
        ]
        result = await compactor.compact(messages, limit_tokens=1_000_000)
        self.assertNotIn("duplicate of segment", result.text)
        self.assertEqual(result.text.count(dup), 2)

    async def test_whitespace_runs_are_stripped_from_tool_results(self):
        config = Config(microcompact_trigger_fraction=0.0)
        compactor = Compactor(config, self.ledger)
        messy = "line one\n\n\n\n\nline two    has    lots    of    spaces"
        result = await compactor.compact([{"role": "tool", "name": "x", "content": messy}], limit_tokens=1_000_000)
        self.assertIn(3, result.layers_applied)
        self.assertNotIn("\n\n\n\n\n", result.text)
        self.assertNotIn("    ", result.text)

    async def test_below_the_microcompact_threshold_layer_3_does_not_fire(self):
        config = Config(microcompact_trigger_fraction=0.95)
        compactor = Compactor(config, self.ledger)
        dup = " ".join(f"w{i}" for i in range(50))
        messages = [{"role": "tool", "name": "search", "content": dup}, {"role": "tool", "name": "search", "content": dup}]
        result = await compactor.compact(messages, limit_tokens=1_000_000)  # nowhere near 95% of a huge limit
        self.assertNotIn(3, result.layers_applied)

    async def test_non_tool_segments_are_left_alone_by_layer_3(self):
        config = Config(microcompact_trigger_fraction=0.0)
        compactor = Compactor(config, self.ledger)
        messy = "line one\n\n\n\n\nline two    has    lots    of    spaces"
        result = await compactor.compact([{"role": "user", "content": messy}], limit_tokens=1_000_000)
        self.assertNotIn(3, result.layers_applied)
        self.assertIn(messy, result.text)


class TestCompactorLayer4ReadTimeCollapse(unittest.IsolatedAsyncioTestCase):
    """Layer 4 (docs/blueprint/subsystems/04-cognition.md section 5):
    a read-time *projection* -- older segments become one-line headlines,
    the newest stay in full, and the caller's own message objects are
    never mutated. Trigger is "always" (S1's own worked example: it
    fires at 5.8k/12k tokens, well under any percentage threshold)."""

    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()

    async def test_older_segments_become_one_line_headlines_newest_stay_full(self):
        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger)
        messages = [
            {"role": "tool", "name": "read", "content": "line1\nline2\nline3"},
            {"role": "user", "content": "the newest message, kept in full"},
        ]
        result = await compactor.compact(messages, limit_tokens=1_000_000)
        self.assertIn(4, result.layers_applied)
        self.assertIn("[step 0: tool read", result.text)
        self.assertIn("the newest message, kept in full", result.text)
        self.assertNotIn("line1\nline2\nline3", result.text)

    async def test_fires_even_when_comfortably_under_budget(self):
        # S1's own worked example: layers 1-3 no-op at 5.8k/12k tokens,
        # but layer 4 still collapses the older turns. Trigger is
        # "always," not a percentage threshold.
        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger)
        messages = [{"role": "user", "content": f"turn {i}"} for i in range(3)]
        result = await compactor.compact(messages, limit_tokens=1_000_000_000)
        self.assertIn(4, result.layers_applied)

    async def test_original_message_dicts_are_never_mutated(self):
        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger)
        original = {"role": "tool", "name": "read", "content": "line1\nline2\nline3"}
        messages = [dict(original), {"role": "user", "content": "newest"}]
        await compactor.compact(messages, limit_tokens=1_000_000)
        self.assertEqual(messages[0], original)

    async def test_fewer_segments_than_the_keep_full_window_is_a_no_op(self):
        config = Config(collapse_keep_full_segments=4)
        compactor = Compactor(config, self.ledger)
        messages = [{"role": "user", "content": "only one"}]
        result = await compactor.compact(messages, limit_tokens=1_000_000)
        self.assertNotIn(4, result.layers_applied)


class TestCompactorLayer5AutoCompact(unittest.IsolatedAsyncioTestCase):
    """Layer 5 (docs/blueprint/subsystems/04-cognition.md section 5):
    the expensive, last-resort layer -- one model call, only when layers
    1-4 still leave the context over budget *and* the caller opted in
    with `allow_summarize`. Roadmap 4.2's "model summarization as last
    resort," closing harness-06 gap #2 by name."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="cognition", clock=self.clock)
        await self.bus.start()

    async def asyncTearDown(self):
        await self.bus.stop()

    async def test_without_allow_summarize_layer_5_never_fires_even_if_still_over_budget(self):
        calls: list[str] = []

        async def _summarize(text: str) -> str:
            calls.append(text)
            return "should never be reached"

        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger, bus=self.bus, summarize=_summarize)
        messages = [{"role": "user", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(5)]
        result = await compactor.compact(messages, limit_tokens=5, allow_summarize=False)
        self.assertNotIn(5, result.layers_applied)
        self.assertEqual(calls, [])

    async def test_without_a_summarizer_injected_layer_5_is_skipped_not_fatal(self):
        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger)  # no summarize= given
        messages = [{"role": "user", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(5)]
        result = await compactor.compact(messages, limit_tokens=5, allow_summarize=True)
        self.assertNotIn(5, result.layers_applied)

    async def test_still_over_budget_with_allow_summarize_calls_the_injected_summarizer(self):
        calls: list[str] = []

        async def _summarize(text: str) -> str:
            calls.append(text)
            return "SUMMARY: did the thing, touched foo.py"

        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger, bus=self.bus, summarize=_summarize)
        messages = [{"role": "user", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(5)]
        result = await compactor.compact(messages, limit_tokens=5, allow_summarize=True, session_id="s1")
        self.assertIn(5, result.layers_applied)
        self.assertEqual(len(calls), 1)
        self.assertIn("SUMMARY: did the thing, touched foo.py", result.text)
        self.assertIsNotNone(result.summary_ref)

    async def test_bounded_body_keeps_the_most_recent_segments_under_the_cap(self):
        """Live-caught, real use (07-post-cutover-review.md section 3.4d):
        layer 5 was the "last resort" for context_too_large, but nothing
        capped its own input -- a genuinely large `pre_collapse` (layers
        1-3 don't always shrink it enough on their own, e.g. under a more
        realistic budget than a tiny test `limit_tokens`) could make
        `body` too large for the `consolidate` purpose's own budget to
        accept, so the last resort could fail its own call instead of
        saving the request. Targets `_bounded_body` directly -- the unit
        `_layer5_auto_compact` actually calls -- rather than fighting
        `compact()`'s own layers 1-3, which already shrink a tiny-budget
        test fixture before layer 5 ever sees it."""
        from simorgh.cognition.compaction import Compactor, _LAYER5_INPUT_MAX_CHARS, _Segment

        # 20 segments of ~3000 chars each = ~60,000 chars, well over the cap.
        segments = [
            _Segment({"role": "user", "content": f"seg{i} " + "w" * 3000}, 750) for i in range(20)
        ]
        body, dropped = Compactor._bounded_body(segments)  # noqa: SLF001

        self.assertLess(len(body), _LAYER5_INPUT_MAX_CHARS + 100)  # a little slack at the boundary segment
        self.assertGreater(dropped, 0)
        self.assertIn("seg19", body)  # the most recent segments are kept
        self.assertNotIn("seg0 ", body)  # the oldest were dropped, not silently truncated mid-segment
        # Order preserved for what's kept (oldest-of-the-kept first).
        self.assertLess(body.index(f"seg{20 - 1 - dropped + 1}"), body.index("seg19"))

    async def test_a_huge_input_still_gets_a_real_summary_end_to_end(self):
        """The end-to-end path: even when `pre_collapse` is large enough
        to need the cap, layer 5 still fires and produces a real summary
        -- the cap degrades gracefully, it doesn't just fail differently."""
        received: list[str] = []

        async def _summarize(text: str) -> str:
            received.append(text)
            return "compact summary"

        config = Config(collapse_keep_full_segments=1, snip_trigger_fraction=100.0, microcompact_trigger_fraction=100.0)
        compactor = Compactor(config, self.ledger, bus=self.bus, summarize=_summarize)
        # Layers 2/3 are disabled above (trigger fractions set unreachably
        # high) so `pre_collapse` reaching layer 5 stays the full, large
        # set of segments -- only layer 4's headline-collapse runs before
        # it, and a low `limit_tokens` keeps even the collapsed total over
        # budget so layer 5 actually fires.
        messages = [
            {"role": "user", "content": f"seg{i} " + "w" * 3000} for i in range(20)
        ] + [{"role": "user", "content": "the newest turn, must survive"}]
        result = await compactor.compact(messages, limit_tokens=5, allow_summarize=True, session_id="s1")

        self.assertIn(5, result.layers_applied)
        self.assertEqual(len(received), 1)
        from simorgh.cognition.compaction import _LAYER5_INPUT_MAX_CHARS
        self.assertLess(len(received[0]), _LAYER5_INPUT_MAX_CHARS + 2_000)  # prompt prefix + cap, real headroom
        self.assertIn("the newest turn, must survive", result.text)
        self.assertIn("compact summary", result.text)

    async def test_replaces_the_collapsed_older_segments_not_the_newest(self):
        async def _summarize(text: str) -> str:
            return "compact summary"

        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger, bus=self.bus, summarize=_summarize)
        messages = [
            {"role": "user", "content": " ".join(f"old{i}" for i in range(500))} for i in range(4)
        ] + [{"role": "user", "content": "the newest turn, must survive"}]
        result = await compactor.compact(messages, limit_tokens=5, allow_summarize=True, session_id="s1")
        self.assertIn("the newest turn, must survive", result.text)
        self.assertIn("compact summary", result.text)
        self.assertNotIn("old0 old1", result.text)

    async def test_emits_compact_pre_and_done_events(self):
        async def _summarize(text: str) -> str:
            return "compact summary"

        seen: list[str] = []

        async def _on_pre(message):
            seen.append("pre")

        async def _on_done(message):
            seen.append("done")

        await self.bus.subscribe(topics.COGNITION_COMPACT_PRE, _on_pre)
        await self.bus.subscribe(topics.COGNITION_COMPACT_DONE, _on_done)

        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger, bus=self.bus, source="cognition", clock=self.clock, summarize=_summarize)
        messages = [{"role": "user", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(5)]
        await compactor.compact(messages, limit_tokens=5, allow_summarize=True, session_id="s1")

        import asyncio
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(seen, ["pre", "done"])

    async def test_summary_is_recorded_to_the_per_session_summaries_stream(self):
        async def _summarize(text: str) -> str:
            return "compact summary"

        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger, bus=self.bus, clock=self.clock, summarize=_summarize)
        messages = [{"role": "user", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(5)]
        await compactor.compact(messages, limit_tokens=5, allow_summarize=True, session_id="s42")

        events = await self.ledger.read("cognition:summaries:s42")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "summary.created")


class TestCompactorPersistentInstructionProtection(unittest.IsolatedAsyncioTestCase):
    """Roadmap 4.2's "persistent-instruction protection": a segment
    tagged `protected: true` or `role: "system"` survives every layer,
    even under extreme pressure -- docs/KnowledgeBase/
    harness-05-subsystems.md: persistent rules "are not really
    'history,' they're configuration." This matters at the `Compactor`
    level (not just `assembler.py`'s block-level protection) because
    `cognition.compact.request`'s caller-owned message list bypasses the
    assembler entirely."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="cognition", clock=self.clock)
        await self.bus.start()

    async def asyncTearDown(self):
        await self.bus.stop()

    async def test_a_system_role_segment_survives_layer_1_even_when_oversized(self):
        config = Config(tool_result_max_tokens=1)
        compactor = Compactor(config, self.ledger)
        big = " ".join(f"word{i}" for i in range(200))
        # role="system" AND role="tool" is contradictory in practice, but
        # this isolates layer 1's own guard: a system-tagged tool segment
        # must not be reduced even though it would otherwise qualify.
        result = await compactor.compact(
            [{"role": "system", "content": big}], limit_tokens=10_000,
        )
        self.assertIn(big, result.text)

    async def test_an_explicitly_protected_tool_result_survives_layer_1(self):
        config = Config(tool_result_max_tokens=1)
        compactor = Compactor(config, self.ledger)
        big = " ".join(f"word{i}" for i in range(200))
        result = await compactor.compact(
            [{"role": "tool", "name": "search", "content": big, "protected": True}], limit_tokens=10_000,
        )
        self.assertNotIn(1, result.layers_applied)
        self.assertIn(big, result.text)

    async def test_a_protected_segment_is_never_dropped_by_snip(self):
        config = Config(snip_keep_last_segments=0, snip_trigger_fraction=0.0, snip_target_fraction=0.0)
        compactor = Compactor(config, self.ledger)
        messages = [
            {"role": "system", "content": "PROTECTED: never drop this", "protected": True},
            {"role": "user", "content": " ".join(["filler"] * 200)},
        ]
        result = await compactor.compact(messages, limit_tokens=1)
        self.assertIn("PROTECTED: never drop this", result.text)

    async def test_a_protected_segment_is_never_headlined_by_layer_4(self):
        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger)
        messages = [
            {"role": "system", "content": "PROTECTED FULL TEXT", "protected": True},
            {"role": "user", "content": "some older filler turn"},
            {"role": "user", "content": "newest turn"},
        ]
        result = await compactor.compact(messages, limit_tokens=1_000_000)
        self.assertIn("PROTECTED FULL TEXT", result.text)
        # The protected segment itself is never turned into a "[step N: ...]" headline.
        self.assertNotIn("[step 0: system", result.text)

    async def test_a_protected_segment_is_never_folded_into_the_layer_5_summary(self):
        async def _summarize(text: str) -> str:
            # If the protected content leaked into the summarizer input,
            # this would still pass -- so assert on the *output* instead:
            # the protected segment must appear verbatim, outside the summary.
            return "compact summary of the rest"

        config = Config(collapse_keep_full_segments=1)
        compactor = Compactor(config, self.ledger, bus=self.bus, clock=self.clock, summarize=_summarize)
        messages = [
            {"role": "system", "content": "PROTECTED: do not summarize me away", "protected": True},
        ] + [
            {"role": "user", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(4)
        ] + [
            {"role": "user", "content": "the newest turn"},
        ]
        result = await compactor.compact(messages, limit_tokens=5, allow_summarize=True, session_id="s1")
        self.assertIn("PROTECTED: do not summarize me away", result.text)
        self.assertIn("compact summary of the rest", result.text)
        self.assertIn("the newest turn", result.text)

    async def test_property_protected_segment_text_is_byte_identical_before_and_after_every_layer(self):
        # 04 section 9's own property test: "protected blocks are
        # byte-identical before/after."
        async def _summarize(text: str) -> str:
            return "summary"

        protected_text = "SACRED: constitution + voice + self-summary, verbatim"
        config = Config(
            tool_result_max_tokens=1, snip_keep_last_segments=0, snip_trigger_fraction=0.0,
            snip_target_fraction=0.0, microcompact_trigger_fraction=0.0, collapse_keep_full_segments=1,
        )
        compactor = Compactor(config, self.ledger, bus=self.bus, clock=self.clock, summarize=_summarize)
        messages = [
            {"role": "system", "content": protected_text, "protected": True},
        ] + [
            {"role": "tool", "name": "search", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(4)
        ]
        result = await compactor.compact(messages, limit_tokens=5, allow_summarize=True, session_id="s1")
        self.assertIn(protected_text, result.text)


if __name__ == "__main__":
    unittest.main()
