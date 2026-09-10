"""A reasoning model needs room to reach an answer.

Thinking tokens come out of the same budget as the answer, so a small
`max_tokens` does not produce a short answer -- it produces NO answer,
and the call fails with `finish_reason='length'` having already been
billed. The `review` purpose asks for 1,000, which made that failure
certain rather than occasional: live on 2026-09-09 every verification
round of a blocked task died this way, and the task never got past its
own retry loop."""

from __future__ import annotations

import json
import unittest

from simorgh.cognition.config import DEFAULT_PURPOSE_BUDGETS
from simorgh.cognition.providers.together import (
    MIN_REASONING_MAX_TOKENS,
    TogetherProvider,
)


class _Transport:
    """The provider's own injection seam -- records the request body and
    returns a canned reply. Same shape the existing Together tests use,
    so this exercises the real request-building path rather than a
    private method."""

    def __init__(self, reply: dict | None = None) -> None:
        self.bodies: list[dict] = []
        self.reply = reply or {
            "id": "x",
            "choices": [{"message": {"role": "assistant", "content": "ok"},
                          "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }

    def __call__(self, url, headers, payload, timeout):
        self.bodies.append(json.loads(payload.decode()))
        return json.dumps(self.reply)


def _provider(transport, **kwargs) -> TogetherProvider:
    return TogetherProvider(api_key="k-test", transport=transport, **kwargs)


async def _ask(provider, *, max_tokens: int):
    return await provider.complete([{"role": "user", "content": "hi"}], tools=None,
                                    max_tokens=max_tokens)


class FloorTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_small_budget_is_raised_to_the_floor(self):
        transport = _Transport()
        await _ask(_provider(transport), max_tokens=1000)
        self.assertEqual(transport.bodies[0]["max_tokens"], MIN_REASONING_MAX_TOKENS)

    async def test_a_generous_budget_is_left_alone(self):
        transport = _Transport()
        await _ask(_provider(transport), max_tokens=8000)
        self.assertEqual(transport.bodies[0]["max_tokens"], 8000)

    async def test_a_non_reasoning_model_keeps_its_small_budget(self):
        """The floor exists for thinking tokens. A model that does not
        think does not need the room, and paying for it would be waste."""
        transport = _Transport()
        await _ask(_provider(transport, reasoning_effort=""), max_tokens=1000)
        self.assertEqual(transport.bodies[0]["max_tokens"], 1000)

    async def test_the_floor_covers_every_purpose_that_was_below_it(self):
        """`review`, `chat`, `decompose` and `reground` all ask for less
        than a reasoning model needs, and all of them go to the same
        provider."""
        below = {name for name, budget in DEFAULT_PURPOSE_BUDGETS.items()
                 if budget.max_tokens_out < MIN_REASONING_MAX_TOKENS}
        self.assertIn("review", below)
        transport = _Transport()
        provider = _provider(transport)
        for name in sorted(below):
            await _ask(provider, max_tokens=DEFAULT_PURPOSE_BUDGETS[name].max_tokens_out)
        for body in transport.bodies:
            self.assertGreaterEqual(body["max_tokens"], MIN_REASONING_MAX_TOKENS)

    async def test_no_cap_at_all_stays_uncapped(self):
        transport = _Transport()
        await _ask(_provider(transport), max_tokens=0)
        self.assertNotIn("max_tokens", transport.bodies[0])


class ReasoningOnlyTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_reply_that_is_all_thinking_is_still_reported_as_a_failure(self):
        """The floor makes this rare, not impossible -- so the honest
        failure it already had must stay."""
        from simorgh.cognition.api import ProviderUnavailable

        transport = _Transport({
            "choices": [{"message": {"content": "", "reasoning_content": "thinking..."},
                         "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4000},
        })
        with self.assertRaises(ProviderUnavailable) as caught:
            await _ask(_provider(transport), max_tokens=1000)
        self.assertIn("too small", str(caught.exception))

    async def test_the_billed_usage_still_travels_with_the_failure(self):
        """The call happened and was charged for; dropping that on the
        floor would understate real spend."""
        from simorgh.cognition.api import ProviderUnavailable

        transport = _Transport({
            "choices": [{"message": {"content": "", "reasoning_content": "..."},
                         "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4000},
        })
        try:
            await _ask(_provider(transport), max_tokens=1000)
        except ProviderUnavailable as exc:
            self.assertIsNotNone(exc.billable)
            self.assertEqual(exc.billable.output_tokens, 4000)
