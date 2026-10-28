"""The Anthropic provider (2026-10-27): Opus 5.5 over the Messages API with
the creator's `SIM_ANTHROPIC_API_KEY`. Every call here goes through the
transport seam; nothing reaches the network."""

from __future__ import annotations

import asyncio
import json
import unittest

from simorgh.cognition.api import ProviderUnavailable
from simorgh.cognition.config import Config
from simorgh.cognition.providers.anthropic import (API_VERSION, MIN_MAX_TOKENS, AnthropicProvider,
                                                   to_anthropic_messages)


def _reply(text="Hello.", stop="end_turn", **usage):
    return json.dumps({"model": "claude-opus-5-5", "stop_reason": stop,
                       "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
                       "usage": {"input_tokens": 100, "output_tokens": 50, **usage}})


class _Wire:
    def __init__(self, answer):
        self.answer, self.sent = answer, []

    def __call__(self, url, headers, body, timeout):
        self.sent.append((url, headers, json.loads(body)))
        return self.answer


def _call(provider, messages, max_tokens=1000):
    return asyncio.run(provider.complete(messages, tools=None, max_tokens=max_tokens))


CHAT = [{"role": "system", "content": "You are Sim."}, {"role": "user", "content": "hi"}]


class TheRequest(unittest.TestCase):
    def test_it_sends_opus_with_the_key_caching_and_room_to_think(self):
        wire = _Wire(_reply())
        reply = _call(AnthropicProvider(api_key="k", transport=wire), CHAT)
        url, headers, body = wire.sent[0]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual((headers["x-api-key"], headers["anthropic-version"]), ("k", API_VERSION))
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["system"], [{"type": "text", "text": "You are Sim.",
                                           "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(body["messages"], [{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
        self.assertEqual(body["cache_control"], {"type": "ephemeral"})
        self.assertEqual(body["max_tokens"], MIN_MAX_TOKENS, "thinking is billed output; 1000 is not room")
        self.assertNotIn("output_config", body, "no effort set: the model's own default")
        self.assertNotIn("thinking", body, "Opus 5.5 always thinks; disabling it is a 400")
        self.assertEqual(reply.text, "Hello.")

    def test_effort_goes_in_output_config(self):
        wire = _Wire(_reply())
        provider = AnthropicProvider(api_key="k", transport=wire)
        provider.set_effort("high")
        _call(provider, CHAT)
        self.assertEqual(wire.sent[0][2]["output_config"], {"effort": "high"})

    def test_no_key_is_unavailable_and_never_calls(self):
        wire = _Wire(_reply())
        provider = AnthropicProvider(api_key="", transport=wire)
        self.assertFalse(provider.available())
        with self.assertRaises(ProviderUnavailable):
            _call(provider, CHAT)
        self.assertEqual(wire.sent, [])


class TheBill(unittest.TestCase):
    def test_cache_reads_writes_and_output_are_priced_apart(self):
        reply = _call(AnthropicProvider(api_key="k", transport=_Wire(_reply(
            cache_read_input_tokens=1_000_000, cache_creation_input_tokens=1_000_000))), CHAT)
        self.assertEqual(reply.cached_input_tokens, 1_000_000)
        self.assertEqual(reply.input_tokens, 1_000_100)
        # 100 in at $4, 50 out at $20, 1M read at $0.20, 1M written at $5.
        self.assertAlmostEqual(reply.cost_usd, 0.0004 + 0.001 + 0.20 + 5.0, places=6)


class Failures(unittest.TestCase):
    def test_a_refusal_and_an_empty_answer_fail_over_with_their_bill(self):
        refused = json.dumps({"stop_reason": "refusal", "stop_details": {"category": "cyber"}, "content": [],
                              "usage": {"input_tokens": 10, "output_tokens": 0}})
        with self.assertRaises(ProviderUnavailable) as caught:
            _call(AnthropicProvider(api_key="k", transport=_Wire(refused)), CHAT)
        self.assertIn("cyber", str(caught.exception))
        self.assertIsNotNone(caught.exception.billable)
        with self.assertRaises(ProviderUnavailable) as caught:
            _call(AnthropicProvider(api_key="k", transport=_Wire(_reply(text="", stop="max_tokens"))), CHAT)
        self.assertTrue(caught.exception.truncated)


class TheMessages(unittest.TestCase):
    def test_roles_merge_start_with_the_user_and_never_end_on_sims_turn(self):
        system, turns = to_anthropic_messages([
            {"role": "system", "content": "a"}, {"role": "assistant", "content": "earlier"},
            {"role": "user", "content": "one"}, {"role": "tool", "content": "result"},
            {"role": "user", "content": "  "}, {"role": "assistant", "content": "partial"}])
        self.assertEqual(system, "a")
        self.assertEqual([t["role"] for t in turns], ["user", "assistant", "user", "assistant", "user"])
        self.assertEqual([b["text"] for b in turns[2]["content"]], ["one", "result"])

    def test_a_growing_turn_keeps_every_earlier_block_byte_for_byte(self):
        """The cache reads only where an earlier request's blocks ended."""
        base = [{"role": "system", "content": "s"}, {"role": "user", "content": "ask"},
                {"role": "assistant", "content": "MAIL_SEARCH: promo"}, {"role": "user", "content": "result 1"}]
        _, before = to_anthropic_messages(base)
        _, after = to_anthropic_messages(base + [{"role": "user", "content": "nudge"}])
        self.assertEqual(after[-1]["content"][:len(before[-1]["content"])], before[-1]["content"])


class TheConfig(unittest.TestCase):
    def test_a_partial_table_keeps_the_dollar_cap_and_prices(self):
        cfg = Config.from_mapping({"providers": {"anthropic": {"reasoning_effort": "high"}}})
        anthropic = cfg.providers["anthropic"]
        self.assertEqual(anthropic.reasoning_effort, "high")
        self.assertEqual(anthropic.max_spend_usd, 5.0)
        self.assertEqual((anthropic.price_in, anthropic.price_out), (4.0, 20.0))
        self.assertNotIn("anthropic", Config().provider_order, "only a config puts it in the order")


if __name__ == "__main__":
    unittest.main()
