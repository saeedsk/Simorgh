"""`benchmark.*` -- standard benchmark suites, run through the same task
path a human's `research` takes, with results kept per model.

The creator, 2026-09-07: "create a benchmarking unit that can benchmark
system against different standard benchmark systems and keep track of
historical benchmark results per model".
"""

from __future__ import annotations

from ..fields import Any_, Bool, F, Float, Int, List, O, Str
from ..registry import define
from .. import topics as t

_RUN_SUMMARY = (
    F("run_id", Str),
    F("suite", Str),
    O("suite_version", Str),
    O("model", Str),
    O("started_at", Float),
    O("finished_at", Float),
    O("attempted", Int),
    O("correct", Int),
    O("skipped", Int),
    O("accuracy", Float),
    O("seconds", Float),
    O("cost_usd", Float),
    O("partial", Bool),
    O("note", Str),
    O("by_level", Any_),
    O("cases", List(Any_)),
    O("detail_ref", Str),
)

BenchmarkSuitesRequest = define(t.BENCHMARK_SUITES_REQUEST, [])
BenchmarkSuitesReply = define(t.BENCHMARK_SUITES_REPLY, [
    F("suites", List(Any_)),
    O("model", Str),
    O("running", Bool),
])
BenchmarkRunRequest = define(t.BENCHMARK_RUN_REQUEST, [
    O("suite", Str),
    O("limit", Int),
    O("level", Str),
    O("refresh", Bool),
    O("note", Str),
], doc="Start a benchmark run. One at a time: two runs would measure each other's contention.")
# `ok`/`error` are added to every `*.reply` by the registry itself.
BenchmarkRunReply = define(t.BENCHMARK_RUN_REPLY, [
    O("run_id", Str),
    O("suite", Str),
    O("suite_version", Str),
    O("cases", Int),
    O("model", Str),
])
BenchmarkLoadRequest = define(t.BENCHMARK_LOAD_REQUEST, [
    F("suite", Str),
    O("refresh", Bool),
], doc="Download a suite's cases without running them.")
BenchmarkLoadReply = define(t.BENCHMARK_LOAD_REPLY, [
    O("suite", Str),
    O("suite_version", Str),
    O("cases", Int),
    O("levels", List(Str)),
    O("needs_attachment", Int),
    O("scorable", Bool),
    O("cache_path", Str),
])
BenchmarkStopRequest = define(t.BENCHMARK_STOP_REQUEST, [], doc="End the benchmark run in flight.")
BenchmarkStopReply = define(t.BENCHMARK_STOP_REPLY, [
    O("stopped", Bool),
    O("run_id", Str),
    O("suite", Str),
    O("detail", Str),
])
BenchmarkProgress = define(t.BENCHMARK_PROGRESS, [
    F("run_id", Str),
    F("suite", Str),
    F("index", Int),
    F("total", Int),
    O("case_id", Str),
    O("level", Str),
    O("correct", Int),
    O("attempted", Int),
    O("elapsed_s", Float),
    # The case just scored, on its own: the running totals above say
    # how the run is going, not what happened to THIS case, and the
    # terminal's one line per case has to say both.
    O("case_correct", Bool),
    O("case_skipped", Bool),
    O("case_seconds", Float),
    O("case_error", Str),
])
BenchmarkRunCompleted = define(t.BENCHMARK_RUN_COMPLETED, list(_RUN_SUMMARY))
BenchmarkHistoryRequest = define(t.BENCHMARK_HISTORY_REQUEST, [
    O("suite", Str),
    O("model", Str),
    O("limit", Int),
    O("run_id", Str),
])
BenchmarkHistoryReply = define(t.BENCHMARK_HISTORY_REPLY, [
    F("runs", List(Any_)),
    O("model", Str),
    O("running", Bool),
    O("progress", Any_),
])

__all__ = [
    "BenchmarkLoadReply", "BenchmarkLoadRequest", "BenchmarkStopReply", "BenchmarkStopRequest",
    "BenchmarkHistoryReply", "BenchmarkHistoryRequest", "BenchmarkProgress", "BenchmarkRunCompleted",
    "BenchmarkRunReply", "BenchmarkRunRequest", "BenchmarkSuitesReply", "BenchmarkSuitesRequest",
]
