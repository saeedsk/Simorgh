"""Stage 17 item 1: `python -m simorgh.telemetry tokens` sums the
`cognition.provider_call` spans of a period into the input split per block
and the cache hit rate, per provider and per lane. A temp telemetry file,
never the live one."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.telemetry import TelemetryStore
from simorgh.telemetry.__main__ import main
from simorgh.telemetry.store import encode, read_spans
from simorgh.telemetry.tokens import BLOCKS, lane_of, parse_since, report, span_blocks

NOW = 1_800_000_000.0


def _split(prefix=0, tools=0, memory=0, question=0, window=0, results=0):
    return {"prefix": prefix, "tools": tools, "memory": memory, "question": question,
            "window": window, "results": results}


class _File(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "telemetry.sqlite"
        self.store = TelemetryStore(self.path)
        self.store.open()
        self.n = 0

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def span(self, *, start=NOW - 60, name="cognition.provider_call", **attrs):
        self.n += 1
        self.store.write([(f"t{self.n}", f"s{self.n}", None, name, start, start + 1.0, "ok", encode(attrs))], [])


class TheSplitOfOneSpan(unittest.TestCase):
    def test_blocks_are_scaled_to_the_providers_count(self):
        scaled, uncached = span_blocks({"tokens_in": 2000, "tokens_cached": 0,
                                        "split": _split(prefix=500, tools=500)})
        self.assertEqual(scaled["prefix"], 1000)
        self.assertEqual(scaled["tools"], 1000)
        self.assertEqual(uncached, scaled)

    def test_the_cache_is_taken_off_the_blocks_in_the_order_sent(self):
        # 1000 cached: all of the prefix (600) and 400 of the tools (500).
        scaled, uncached = span_blocks({"tokens_in": 2000, "tokens_cached": 1000,
                                        "split": _split(prefix=600, tools=500, question=100, window=800)})
        self.assertEqual(uncached["prefix"], 0)
        self.assertEqual(uncached["tools"], 100)
        self.assertEqual(uncached["question"], 100)
        self.assertEqual(uncached["window"], 800)
        self.assertEqual(sum(uncached.values()), 1000)

    def test_a_span_without_a_split_has_none(self):
        self.assertIsNone(span_blocks({"tokens_in": 10}))
        self.assertIsNone(span_blocks({"tokens_in": 10, "split": _split()}))

    def test_lanes(self):
        self.assertEqual(lane_of({"purpose": "chat"}), "chat")
        self.assertEqual(lane_of({"purpose": "chat", "channel": "voice"}), "voice")
        self.assertEqual(lane_of({"purpose": "draft"}), "task")

    def test_since(self):
        self.assertEqual(parse_since("7d"), 7 * 86_400)
        self.assertEqual(parse_since("12h"), 12 * 3600)
        self.assertEqual(parse_since("90"), 90)
        with self.assertRaises(ValueError):
            parse_since("a week")


class TheReport(_File):
    def test_per_provider_and_per_lane_with_the_cache_hit_rate(self):
        self.span(provider="together", purpose="chat", tokens_in=1000, tokens_cached=600, tokens_out=50,
                  split=_split(prefix=400, tools=300, question=100, window=200))
        self.span(provider="together", purpose="draft", tokens_in=3000, tokens_cached=0, tokens_out=200,
                  split=_split(prefix=400, tools=300, results=2300))
        self.span(provider="gemini", purpose="chat", channel="voice", tokens_in=500, tokens_cached=0,
                  split=_split(prefix=250, tools=250))
        self.span(provider="together", purpose="chat", tokens_in=100)               # before the split existed
        self.span(provider="together", purpose="chat", tokens_in=999, start=NOW - 10 * 86_400)  # outside 7d
        self.span(name="something.else", provider="together", tokens_in=999)

        result = report(self.path, since_s=7 * 86_400, now=NOW)
        together = result["by_provider"]["together"]
        self.assertEqual(together["calls"], 3)
        self.assertEqual(together["split_calls"], 2)
        self.assertEqual(together["tokens_in"], 4100)
        self.assertAlmostEqual(together["cache_hit"], 600 / 4100)
        self.assertEqual(result["by_provider"]["gemini"]["tokens_in"], 500)
        self.assertEqual(set(result["by_lane"]), {"chat", "task", "voice"})
        chat = result["by_lane"]["chat"]
        # prefix 400 cached in full, 200 of tools' 300 cached.
        self.assertEqual(chat["uncached"]["prefix"], 0)
        self.assertEqual(chat["uncached"]["tools"], 100)
        self.assertAlmostEqual(chat["uncached_share"]["tools"], 100 / 400)
        self.assertAlmostEqual(sum(chat["share"].values()), 1.0)
        self.assertAlmostEqual(result["by_lane"]["voice"]["uncached_share"]["tools"], 0.5)

    def test_the_command_prints_the_split_and_the_gate(self):
        self.span(provider="together", purpose="chat", tokens_in=1000, tokens_cached=0,
                  split=_split(prefix=500, tools=300, question=200))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["tokens", "--since", "7d", "--file", str(self.path)]), 0)
        text = out.getvalue()
        self.assertIn("provider together: 1 calls", text)
        self.assertIn("0% hit", text)
        for block in BLOCKS:
            self.assertIn(block, text)
        self.assertIn("gate (chat): tools are 30.0% of uncached input (over 20%)", text)

    def test_json(self):
        self.span(provider="p", purpose="chat", tokens_in=10, split=_split(prefix=10), start=time.time() - 5)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["tokens", "--file", str(self.path), "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["all"]["calls"], 1)

    def test_a_missing_file_says_so(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["tokens", "--file", str(Path(self._tmp.name) / "none.sqlite")]), 1)
        self.assertIn("no telemetry file", err.getvalue())

    def test_read_spans_is_read_only_and_filters_by_name_and_start(self):
        self.span(provider="a", start=NOW - 100)
        self.span(provider="b", start=NOW - 10)
        self.span(name="other", provider="c", start=NOW - 10)
        rows = read_spans(self.path, "cognition.provider_call", since=NOW - 50)
        self.assertEqual([r["attrs"]["provider"] for r in rows], ["b"])
        self.assertEqual(read_spans(Path(self._tmp.name) / "absent.sqlite", "x"), [])


if __name__ == "__main__":
    unittest.main()
