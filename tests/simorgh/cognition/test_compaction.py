"""The graduated compaction pipeline, layers 1-2 (docs/blueprint/
subsystems/04-cognition.md section 5): cheap, non-destructive
interventions before anything lossy. Each layer is tested in isolation
and then as a pipeline, per this build's own scope note in
`simorgh/cognition/compaction.py`."""

from __future__ import annotations

import unittest

from simorgh.cognition.compaction import Compactor
from simorgh.cognition.config import Config
from simorgh.ledger.factory import make_ledger


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

    async def test_allow_summarize_flag_is_accepted_but_layers_3_plus_are_not_yet_built(self):
        # Explicit acceptance-bar note: this build scope is layers 1-2
        # only (see the package docstring) -- passing allow_summarize=True
        # must not raise, but it also must not silently claim a layer
        # that doesn't exist yet.
        config = Config()
        compactor = Compactor(config, self.ledger)
        result = await compactor.compact([{"role": "user", "content": "hi"}], limit_tokens=10_000, allow_summarize=True)
        self.assertNotIn(3, result.layers_applied)
        self.assertNotIn(4, result.layers_applied)
        self.assertNotIn(5, result.layers_applied)


if __name__ == "__main__":
    unittest.main()
