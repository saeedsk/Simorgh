"""The `benchmark` command and the dashboard endpoint."""

from __future__ import annotations

import json
import unittest

from simorgh.benchmark.api import CaseResult, RunRecord
from simorgh.interface import benchmarkview as view
from simorgh.interface.parser import parse


def _run(model="glm", suite="gaia", correct=(True, True, False), started=1.0) -> dict:
    record = RunRecord(suite=suite, model=model, started_at=started, suite_version="v1")
    for index, ok in enumerate(correct):
        record.results.append(CaseResult(case_id=f"c{index}", level=str(index % 3 + 1), correct=ok,
                                         expected="Paris", answer="Paris" if ok else "Berlin", seconds=2.0))
    return record.to_payload()


class ParsingTestCase(unittest.TestCase):
    def test_benchmark_is_a_real_command(self):
        command = parse("benchmark run gaia 5")
        self.assertEqual(command.name, "benchmark")
        self.assertEqual(command.args, "run gaia 5")

    def test_a_suite_alone_is_enough(self):
        payload, problem = view.parse_run("gaia")
        self.assertEqual(problem, "")
        self.assertEqual(payload, {"suite": "gaia"})

    def test_a_count_a_level_and_refresh_are_all_optional(self):
        payload, problem = view.parse_run("gaia 25 level=2 refresh")
        self.assertEqual(problem, "")
        self.assertEqual(payload, {"suite": "gaia", "limit": 25, "level": "2", "refresh": True})

    def test_the_order_of_the_options_does_not_matter(self):
        payload, _ = view.parse_run("level=1 refresh bfcl-parallel 8")
        self.assertEqual(payload, {"suite": "bfcl-parallel", "limit": 8, "level": "1", "refresh": True})

    def test_no_suite_is_a_usage_message(self):
        payload, problem = view.parse_run("")
        self.assertEqual(payload, {})
        self.assertIn("usage", problem)


class RenderingTestCase(unittest.TestCase):
    def test_latest_summarises_each_suite_and_model(self):
        text = view.latest({"runs": [_run(model="glm"), _run(model="other", started=2.0)]})
        self.assertIn("glm", text)
        self.assertIn("other", text)
        self.assertIn("2/3 correct", text)

    def test_latest_with_nothing_tells_you_how_to_start(self):
        self.assertIn("benchmark run", view.latest({"runs": []}))

    def test_a_run_in_flight_is_reported(self):
        text = view.latest({
            "runs": [_run()], "running": True,
            "progress": {"suite": "gaia", "index": 3, "total": 10, "correct": 2, "attempted": 2},
        })
        self.assertIn("in flight: gaia 3/10", text)

    def test_history_draws_a_chart_and_a_comparison(self):
        text = view.history({"runs": [
            _run(correct=(True, False, False), started=1.0),
            _run(correct=(True, True, True), started=2.0),
        ]})
        self.assertTrue(any(0x2800 <= ord(ch) <= 0x28FF for ch in text), "no braille chart")
        self.assertIn("fixed   2", text)

    def test_suites_names_what_is_gated_and_what_is_load_only(self):
        text = view.suites({"model": "glm", "suites": [
            {"name": "gaia", "dataset": "gaia-benchmark/GAIA", "description": "d",
             "gated": True, "scorable": True, "cached_cases": 0},
            {"name": "swebench-verified", "dataset": "SWE-bench/SWE-bench_Verified", "description": "d",
             "gated": False, "scorable": False, "why_not_scorable": "needs containers", "cached_cases": 12},
        ]})
        self.assertIn("gated", text)
        self.assertIn("not downloaded", text)
        self.assertIn("load-only", text)
        self.assertIn("12 cached", text)
        self.assertIn("needs containers", text)

    def test_detail_shows_every_case_with_a_mark(self):
        text = view.detail({"runs": [_run()]})
        self.assertIn("✓ c0", text)
        self.assertIn("✗ c2", text)
        self.assertIn("Berlin", text)

    def test_detail_of_nothing_says_so(self):
        self.assertEqual(view.detail({"runs": []}), "no such run")

    def test_started_names_the_run_and_the_model(self):
        text = view.started({"suite": "gaia", "cases": 10, "model": "glm", "run_id": "abc"})
        self.assertIn("gaia", text)
        self.assertIn("10 cases", text)
        self.assertIn("abc", text)


class DashboardTestCase(unittest.TestCase):
    def test_the_page_has_the_benchmark_chart_and_polls_the_endpoint(self):
        from pathlib import Path

        page = (Path(__file__).resolve().parents[3] / "simorgh" / "interface" / "static" / "dashboard.html").read_text()
        self.assertIn('id="bench-svg"', page)
        self.assertIn("/api/benchmarks", page)
        self.assertIn("refreshBenchmarks", page)
        self.assertIn("renderBenchmarks", page)

    def test_the_payload_the_page_reads_is_the_one_the_record_writes(self):
        payload = _run()
        for key in ("accuracy", "correct", "attempted", "by_level", "model", "suite", "started_at"):
            self.assertIn(key, payload)
        self.assertIsInstance(json.dumps(payload), str)


if __name__ == "__main__":
    unittest.main()
