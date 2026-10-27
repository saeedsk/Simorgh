"""Stage 17 item 3: `python -m simorgh.telemetry routing` sums the
`routing.shadow` spans orchestration writes per routed chat turn
(`session.py::_route_done`) into turns, the miss rate, the
conversational-route-then-tool rate and per-group offered/used counts.
Hand-built spans in a temp telemetry file, never the live one."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from simorgh.telemetry import TelemetryStore
from simorgh.telemetry.__main__ import main
from simorgh.telemetry.routing import report, summarize
from simorgh.telemetry.store import encode

NOW = 1_800_000_000.0


def _turn(offered, used=(), used_groups=(), missed=(), conversational=False, channel=""):
    return {"offered": list(offered), "used": list(used), "used_groups": list(used_groups),
            "missed": list(missed), "more": [], "conversational": conversational,
            "tools_offered": 10, "channel": channel}


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

    def span(self, attrs, *, start=NOW - 60, name="routing.shadow"):
        self.n += 1
        self.store.write([(f"t{self.n}", f"s{self.n}", None, name, start, start, "ok", encode(attrs))], [])

    def four_turns(self):
        # A light turn routed right; a light turn that also used a security
        # tool the route left out (a miss); a thanks that stayed toolless; a
        # thanks after which the model still called a tool (a miss too).
        self.span(_turn(["home", "memory"], ["home_light"], ["home"]))
        self.span(_turn(["home", "memory"], ["home_light", "sec_posture"], ["home", "security"],
                        missed=["sec_posture"], channel="voice"))
        self.span(_turn(["memory"], conversational=True))
        self.span(_turn(["memory"], ["web_search"], ["web"], missed=["web_search"], conversational=True))


class TheSummary(unittest.TestCase):
    def test_no_turns_is_zero_not_a_division(self):
        out = summarize([])
        self.assertEqual((out["turns"], out["miss_rate"], out["conversational_then_tool_rate"]), (0, 0.0, 0.0))

    def test_malformed_attributes_count_as_a_turn_with_nothing(self):
        out = summarize([{"attrs": {"offered": "home", "used": None}}, {"attrs": None}])
        self.assertEqual(out["turns"], 2)
        self.assertEqual(out["groups"], {})


class TheReport(_File):
    def test_turns_miss_rate_conversational_and_groups(self):
        self.four_turns()
        self.span(_turn(["home"], ["x"], missed=["x"]), start=NOW - 10 * 86_400)  # outside 7d
        self.span(_turn(["home"], ["x"], missed=["x"]), name="routing.on")        # the other mode
        result = report(self.path, since_s=7 * 86_400, now=NOW)
        self.assertEqual(result["turns"], 4)
        self.assertEqual(result["tool_turns"], 3)
        self.assertEqual(result["missed_turns"], 2)
        self.assertAlmostEqual(result["miss_rate"], 0.5)
        self.assertEqual((result["conversational"], result["conversational_then_tool"]), (2, 1))
        self.assertAlmostEqual(result["conversational_then_tool_rate"], 0.5)
        self.assertEqual(result["groups"]["home"], {"offered": 2, "used": 2})
        self.assertEqual(result["groups"]["memory"], {"offered": 4, "used": 0})
        self.assertEqual(result["groups"]["security"], {"offered": 0, "used": 1})
        self.assertEqual(result["missed_tools"], {"sec_posture": 1, "web_search": 1})
        self.assertEqual(result["by_channel"]["voice"], {"turns": 1, "missed_turns": 1})
        self.assertEqual(result["by_channel"]["typed"], {"turns": 3, "missed_turns": 1})

    def test_on_mode_reads_its_own_spans(self):
        self.four_turns()
        self.span(_turn(["home"], ["home_light"], ["home"]), name="routing.on")
        result = report(self.path, since_s=7 * 86_400, mode="on", now=NOW)
        self.assertEqual((result["turns"], result["missed_turns"]), (1, 0))

    def test_the_command_prints_the_rates_groups_and_gate(self):
        import time
        for attrs in (_turn(["home", "memory"], ["home_light"], ["home"]),
                      _turn(["memory"], ["web_search"], ["web"], missed=["web_search"], conversational=True)):
            self.span(attrs, start=time.time() - 5)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["routing", "--since", "7d", "--file", str(self.path)]), 0)
        text = out.getvalue()
        self.assertIn("turns: 2 (2 used a tool)", text)
        self.assertIn("miss rate: 50.0% (1 of 2 turns", text)
        self.assertIn("conversational route then a tool: 100.0% (1 of 1 conversational turns)", text)
        self.assertRegex(text, r"home\s+1\s+1")
        self.assertRegex(text, r"web\s+0\s+1")
        self.assertIn("web_search 1", text)
        self.assertIn("gate: miss rate 50.0% is not under 3%", text)

    def test_json_and_an_empty_period(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["routing", "--file", str(self.path), "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["turns"], 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["routing", "--file", str(self.path)]), 0)
        self.assertIn("no routed turns", out.getvalue())

    def test_a_missing_file_says_so(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["routing", "--file", str(Path(self._tmp.name) / "none.sqlite")]), 1)
        self.assertIn("routing: no telemetry file", err.getvalue())


if __name__ == "__main__":
    unittest.main()
