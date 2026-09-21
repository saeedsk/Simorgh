"""What Sim learns about its own tools from using them (stage 6 item 1).

`action.result` carries the tool, whether it worked and how long it
took, on every single call. World Model was already subscribed to it
-- and threw all three away unless the tool was `home_call`, because
that handler was written for the house.

So the one thing Sim could learn about itself from ordinary use, at
no cost and with thousands of samples, was being discarded on the
first line of the one handler that saw it.
"""

import unittest

from simorgh.worldmodel.selfmodel import (
    Identity, SelfModel, TOOL_SAMPLES, observe_tool, render_summary, slow_or_unreliable,
)


def _model() -> SelfModel:
    return SelfModel(version=1, updated_at=0.0,
                     identity=Identity(name="Sim", soul_sha256="x", directives=(), summary="s"))


class CountingCalls(unittest.TestCase):
    def test_a_rate_and_a_sample_count_together(self):
        model = _model()
        for i in range(10):
            model = observe_tool(model, tool="web_fetch", ok=(i % 2 == 0), duration_ms=100, updated_at=1.0)
        entry = model.tools["web_fetch"]
        self.assertEqual((entry["runs"], entry["ok"], entry["p_ok"]), (10, 5, 0.5))

    def test_a_refused_call_counts(self):
        """A tool Guardian stops half the time is one to plan around
        differently. Counting only the calls that ran would make the
        number flattering rather than useful."""
        model = observe_tool(_model(), tool="run_shell", ok=False, duration_ms=1, updated_at=1.0)
        self.assertEqual(model.tools["run_shell"]["p_ok"], 0.0)

    def test_a_nameless_tool_is_not_a_tool(self):
        self.assertEqual(observe_tool(_model(), tool="", ok=True, duration_ms=1, updated_at=1.0).tools, {})

    def test_tools_are_kept_apart(self):
        model = observe_tool(_model(), tool="a", ok=True, duration_ms=1, updated_at=1.0)
        model = observe_tool(model, tool="b", ok=False, duration_ms=1, updated_at=1.0)
        self.assertEqual(sorted(model.tools), ["a", "b"])


class HowLongItTakes(unittest.TestCase):
    def test_the_quantiles_come_from_the_samples(self):
        model = _model()
        for ms in range(1, 101):
            model = observe_tool(model, tool="t", ok=True, duration_ms=float(ms), updated_at=1.0)
        entry = model.tools["t"]
        self.assertGreater(entry["p95_ms"], entry["p50_ms"])

    def test_the_sample_list_is_bounded(self):
        """Keeping every duration ever measured would grow the self
        model without bound for a number nobody reads to three
        decimal places."""
        model = _model()
        for i in range(TOOL_SAMPLES * 3):
            model = observe_tool(model, tool="t", ok=True, duration_ms=float(i + 1), updated_at=1.0)
        self.assertEqual(len(model.tools["t"]["recent_ms"]), TOOL_SAMPLES)

    def test_a_zero_duration_is_not_a_measurement(self):
        """Some results carry no duration at all; averaging zeros in
        would say every tool is instant."""
        model = observe_tool(_model(), tool="t", ok=True, duration_ms=0.0, updated_at=1.0)
        self.assertEqual(model.tools["t"]["recent_ms"], [])
        self.assertEqual(model.tools["t"]["runs"], 1, "the call still happened")


class WhichOnesAreWorthSaying(unittest.TestCase):
    def test_one_bad_first_call_does_not_condemn_a_tool(self):
        """The interesting failure of a number like this is a tool
        that failed once, on its first call, and is reported as 0%
        forever after."""
        model = observe_tool(_model(), tool="t", ok=False, duration_ms=10, updated_at=1.0)
        self.assertEqual(slow_or_unreliable(model), [])

    def test_an_unreliable_tool_is_named(self):
        model = _model()
        for i in range(10):
            model = observe_tool(model, tool="web_fetch", ok=(i % 3 != 0), duration_ms=100, updated_at=1.0)
        [row] = slow_or_unreliable(model)
        self.assertEqual(row["tool"], "web_fetch")
        self.assertTrue(row["unreliable"])
        self.assertFalse(row["slow"])

    def test_a_slow_but_reliable_tool_is_named_as_slow(self):
        model = _model()
        for _ in range(10):
            model = observe_tool(model, tool="run_tests", ok=True, duration_ms=45_000, updated_at=1.0)
        [row] = slow_or_unreliable(model)
        self.assertTrue(row["slow"])
        self.assertFalse(row["unreliable"])

    def test_a_fast_reliable_tool_is_not_mentioned_at_all(self):
        model = _model()
        for _ in range(50):
            model = observe_tool(model, tool="read_file", ok=True, duration_ms=4, updated_at=1.0)
        self.assertEqual(slow_or_unreliable(model), [])


class ItReachesTheSummary(unittest.TestCase):
    def test_the_summary_names_the_rough_ones_with_their_counts(self):
        model = _model()
        for i in range(12):
            model = observe_tool(model, tool="web_fetch", ok=(i % 3 != 0), duration_ms=200, updated_at=1.0)
        text, _tokens = render_summary(model, 400)
        self.assertIn("web_fetch", text)
        self.assertIn("over 12", text, "a rate without a sample count is not a number")

    def test_nothing_rough_means_no_section(self):
        model = _model()
        for _ in range(20):
            model = observe_tool(model, tool="read_file", ok=True, duration_ms=3, updated_at=1.0)
        self.assertNotIn("Tools to plan around", render_summary(model, 400)[0])


class ItSurvivesARestart(unittest.TestCase):
    def test_the_table_round_trips(self):
        model = observe_tool(_model(), tool="web_fetch", ok=True, duration_ms=120, updated_at=1.0)
        back = SelfModel.from_dict(model.to_dict())
        self.assertEqual(back.tools["web_fetch"]["runs"], 1)

    def test_an_old_snapshot_with_no_tools_key_still_loads(self):
        data = _model().to_dict()
        data.pop("tools", None)
        self.assertEqual(SelfModel.from_dict(data).tools, {})


if __name__ == "__main__":
    unittest.main()
