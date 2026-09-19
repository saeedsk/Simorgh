"""The `Telemetry` protocol and its no-op (stage 1 item 1): every
Context has a `telemetry`, a hand-built one records nothing, and the
no-op still lets a span's exception through."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import pytest

from simorgh.contracts.protocols import NULL_TELEMETRY, Context, NullTelemetry, Span, Telemetry

pytestmark = [pytest.mark.contract]


class TheNoOp(unittest.IsolatedAsyncioTestCase):
    async def test_it_conforms_and_records_nothing(self):
        telemetry = NullTelemetry()
        self.assertIsInstance(telemetry, Telemetry)
        async with telemetry.span("x", trace_id="t", attrs={"a": 1}) as span:
            self.assertIsInstance(span, Span)
            self.assertEqual((span.name, span.trace_id, span.parent_id), ("x", "t", None))
            span.set("k", "v")
        telemetry.sample("s", 1.0)
        telemetry.sample("s", {"a": 1}, ts=5.0)
        self.assertEqual(await telemetry.query("t"), [])

    async def test_an_exception_in_the_body_is_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            async with NULL_TELEMETRY.span("x", trace_id="t"):
                raise RuntimeError("boom")


class TheContext(unittest.TestCase):
    def test_a_context_built_by_hand_carries_the_no_op(self):
        ctx = Context(name="n", instance_id="", run_id="r", mode="single", bus=mock.Mock(), ledger=mock.Mock(),
                      config={}, secrets={}, clock=mock.Mock(), logger=mock.Mock(), data_dir=Path("."))
        self.assertIs(ctx.telemetry, NULL_TELEMETRY)


if __name__ == "__main__":
    unittest.main()
