"""The `benchmark` command and the dashboard endpoint."""

from __future__ import annotations

import json
import unittest
import unittest.mock

from simorgh.benchmark.api import CaseResult, RunRecord
from simorgh.interface import benchmarkview as view
from simorgh.interface.dispatch import _BENCHMARK_USAGE
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


class ProgressViewTestCase(unittest.TestCase):
    def test_the_in_flight_view_carries_elapsed_seconds_not_monotonic_stamps(self):
        """The service's `_running` holds `time.monotonic()` stamps,
        which mean nothing to a reader in another process; the view a
        `benchmark` reply carries turns them into seconds elapsed, for
        both the run and the case now in flight."""
        from simorgh.benchmark.service import Service

        service = Service()
        self.assertEqual(service._progress_view(), {})
        with unittest.mock.patch("simorgh.benchmark.service.time.monotonic", return_value=1000.0):
            service._running = {"run_id": "r", "suite": "gaia", "index": 1, "total": 3, "started": 400.0,
                                "case": "c2", "level": "2", "case_started": 940.0}
            view_ = service._progress_view()
        self.assertEqual(view_["elapsed_s"], 600.0)
        self.assertEqual(view_["case_elapsed_s"], 60.0)
        self.assertEqual(view_["case"], "c2")
        self.assertNotIn("started", view_)
        self.assertNotIn("case_started", view_)


class CompareCandidatesTestCase(unittest.TestCase):
    def test_the_last_two_scored_runs_per_suite_get_their_cases(self):
        """`history` compares the two most recent runs that scored
        something; a run interrupted before any case must not take one
        of those two slots, or the comparison is against no cases at
        all -- `over 0 shared cases` for two runs of the same two cases
        (observer swe-01, 2026-09-10)."""
        from simorgh.benchmark.service import _compare_candidates

        runs = [
            {"suite": "s", "attempted": 2}, {"suite": "s", "attempted": 2},
            {"suite": "s", "attempted": 1, "partial": True}, {"suite": "s", "attempted": 0, "partial": True},
            {"suite": "t", "attempted": 3},
        ]
        self.assertEqual(_compare_candidates(runs), [1, 2, 4])
        self.assertEqual(_compare_candidates([{"suite": "s", "attempted": 0}]), [])

    def test_a_partial_run_in_the_comparison_is_named(self):
        full = _run(correct=(True, True), started=1.0)
        part = _run(correct=(True,), started=2.0)
        part["partial"] = True
        text = view.history({"runs": [full, part]})
        self.assertIn("over 1 shared cases", text)
        self.assertIn(f"{part['run_id']} is partial (1 case scored)", text)


class RenderingTestCase(unittest.TestCase):
    def test_latest_summarises_each_suite_and_model(self):
        text = view.latest({"runs": [_run(model="glm"), _run(model="other", started=2.0)]})
        self.assertIn("glm", text)
        self.assertIn("other", text)
        self.assertIn("2/3", text)

    def test_latest_with_nothing_tells_you_how_to_start(self):
        self.assertIn("benchmark run", view.latest({"runs": []}))

    def test_a_run_in_flight_is_reported(self):
        text = view.latest({
            "runs": [_run()], "running": True,
            "progress": {"suite": "gaia", "index": 3, "total": 10, "correct": 2, "attempted": 2},
        })
        self.assertIn("in flight: gaia 3/10", text)

    def test_a_run_in_flight_names_the_case_and_how_long(self):
        """Typed mid-run through the terminal (observer swe-01,
        2026-09-10), `benchmark` answered `in flight: swebench-verified
        0/2  0/0 correct so far` for the whole ten minutes the first
        case took: true, and useless -- nothing named the case or said
        how long anything had been going."""
        text = view.latest({
            "runs": [_run()], "running": True,
            "progress": {"suite": "swebench-verified", "index": 0, "total": 2, "correct": 0, "attempted": 0,
                         "case": "astropy__astropy-14309", "level": "<15 min fix",
                         "case_elapsed_s": 95.0, "elapsed_s": 641.0},
        })
        self.assertIn("in flight: swebench-verified 0/2", text)
        self.assertIn("now on astropy__astropy-14309 (<15 min fix) for 1m35s", text)
        self.assertIn("run started 10m41s ago", text)

    def test_after_the_last_case_nothing_is_in_flight_to_name(self):
        text = view.latest({
            "runs": [_run()], "running": True,
            "progress": {"suite": "gaia", "index": 2, "total": 2, "correct": 1, "attempted": 2,
                         "case": "c2", "elapsed_s": 30.0},
        })
        self.assertNotIn("now on", text)

    def test_one_line_per_scored_case(self):
        """`benchmark run` says progress is narrated as it goes; this is
        the line that narrates it, and it has to say the verdict of THIS
        case, not just the running total."""
        base = {"run_id": "r", "suite": "swebench-verified", "index": 1, "total": 2,
                "case_id": "astropy__astropy-14309", "level": "<15 min fix", "correct": 1, "attempted": 1}
        line = view.progress_line({**base, "case_correct": True, "case_seconds": 612.4})
        self.assertIn("benchmark 1/2 · astropy__astropy-14309 (<15 min fix) · resolved in 10m12s · 1/1 so far", line)
        line = view.progress_line({**base, "correct": 0, "case_correct": False, "case_seconds": 40.0,
                                   "case_error": "2 test(s) still failing"})
        self.assertIn("unresolved in 40s · 0/1 so far -- 2 test(s) still failing", line)
        line = view.progress_line({**base, "correct": 0, "attempted": 0, "case_skipped": True,
                                   "case_error": "the Docker daemon is not running"})
        self.assertIn("skipped", line)
        self.assertIn("Docker daemon", line)
        line = view.progress_line({**base, "suite": "gaia", "case_correct": True, "case_seconds": 3.0})
        self.assertIn("correct in 3s", line)

    def test_a_run_interrupted_before_any_case_is_named_not_plotted_as_zero(self):
        """Ctrl-C twenty seconds into a run leaves a partial record with
        0 attempted cases -- rightly. After the restart `benchmark
        history` read `0.0%  (4 runs)  ▼100.0pt` and the compare block
        `(100.0%) → (0.0%)  ▼100.0pt over 0 shared cases` for a model
        that had resolved every case it was ever asked (observer swe-01,
        2026-09-10). An empty run is counted, never scored."""
        full = _run(correct=(True, True), started=1.0)
        empty = _run(correct=(), started=2.0)
        empty["partial"] = True
        text = view.history({"runs": [full, empty]})
        self.assertNotIn("▼100", text)
        self.assertNotIn("0.0%", text.replace("100.0%", ""))
        self.assertIn("100.0%", text)
        self.assertIn("1 run interrupted before any case was scored", text)
        # And `benchmark` on its own shows the run that scored something.
        latest = view.latest({"runs": [full, empty]})
        self.assertIn("2/2", latest)
        self.assertIn("interrupted before any case was scored", latest)
        # Nothing but empty runs: say so rather than draw a 0% chart.
        self.assertIn("interrupted", view.history({"runs": [empty]}))
        self.assertNotIn("0.0%", view.history({"runs": [empty]}))

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


def _dispatch_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[3] / "simorgh" / "interface" / "dispatch.py").read_text()


class LoadVerbTestCase(unittest.TestCase):
    """`benchmark load` downloads a suite without running it. It exists
    because the suites listing advertised it before it did (2026-09-08),
    and because checking a token works should not cost model calls."""

    def test_it_reports_the_shape_of_what_it_downloaded(self):
        text = view.loaded({
            "suite": "gaia", "suite_version": "abc", "cases": 165,
            "levels": ["1", "2", "3"], "needs_attachment": 38, "scorable": True,
            "cache_path": "/home/x/.simorgh/benchmarks/gaia.json",
        })
        self.assertIn("165 cases", text)
        self.assertIn("revision abc", text)
        self.assertIn("1, 2, 3", text)
        self.assertIn("38 need a file", text)
        self.assertIn("/home/x/.simorgh/benchmarks/gaia.json", text)

    def test_a_load_only_suite_says_run_will_refuse_it(self):
        text = view.loaded({"suite": "swebench-verified", "cases": 500, "levels": [],
                            "needs_attachment": 0, "scorable": False, "cache_path": "/tmp/x"})
        self.assertIn("load-only", text)
        self.assertIn("refuse", text)

    def test_a_suite_with_no_missing_files_does_not_mention_them(self):
        text = view.loaded({"suite": "bfcl-parallel", "cases": 3, "levels": ["parallel"],
                            "needs_attachment": 0, "scorable": True, "cache_path": "/tmp/x"})
        self.assertNotIn("need a file", text)

    def test_the_usage_line_advertises_only_verbs_that_exist(self):
        from simorgh.interface.dispatch import BENCHMARK_VERBS

        advertised = {verb for verb, _args, _what in BENCHMARK_VERBS if verb}
        self.assertEqual(advertised, {"suites", "load", "run", "stop", "history", "show"})
        for verb in advertised:
            self.assertIn(f'verb == "{verb}"', _dispatch_source(), f"{verb} is advertised but not handled")
        self.assertIn("benchmark load <suite>", _BENCHMARK_USAGE)


class StopVerbTestCase(unittest.TestCase):
    """`benchmark stop` ends the run in flight and keeps what it scored.

    The creator hit "already_running" and the message named neither how
    far along the run was nor how to end it (2026-09-08)."""

    def test_it_reports_the_detail_the_subsystem_gave(self):
        text = view.stopped({"stopped": True, "run_id": "abc", "suite": "gaia",
                             "detail": "stopped after 3 of 20 cases; the partial result is recorded"})
        self.assertIn("3 of 20", text)
        self.assertIn("partial result is recorded", text)

    def test_nothing_in_flight_says_so(self):
        self.assertIn("no benchmark run", view.stopped({"stopped": False, "detail": "no benchmark run is in flight"}))

    def test_a_bare_reply_still_renders(self):
        self.assertEqual(view.stopped({"stopped": False}), "nothing to stop")
