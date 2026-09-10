"""The benchmark unit end to end, in two halves.

The `Runner` is exercised against a bus with one scripted answerer, so
what is being tested is the harness -- one task per case, the answer
scored, an unanswerable case skipped -- and not whichever of Planning or
a stub replied first. The subsystem's own request/reply wiring is then
tested over a real Kernel, where the interesting cases are the refusals:
a gated suite with no token, and a suite we cannot score honestly.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from simorgh.benchmark import datasets as datasets_mod
from simorgh.benchmark.api import Case, Suite
from simorgh.benchmark.config import Config
from simorgh.benchmark.runner import Runner
from simorgh.benchmark.store import RunStore
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.ledger.factory import make_ledger

from tests.simorgh.orchestration.harness import Harness

SUITE = Suite(name="toy", version="v1", cases=(
    Case(id="c1", question="what is 2+2", answer="4", level="1", suite="toy"),
    Case(id="c2", question="capital of France", answer="Paris", level="2", suite="toy"),
    Case(id="c3", question="needs a file", answer="x", level="3", suite="toy", attachment="sheet.xlsx"),
))
ANSWERS = {"what is 2+2": "FINAL ANSWER: 4", "capital of France": "FINAL ANSWER: Berlin"}


class _Answerer:
    """One scripted stand-in for Planning plus a Worker."""

    def __init__(self, bus, *, complete: bool = True, delay: float = 0.0) -> None:
        self._bus = bus
        self._complete = complete
        self._delay = delay
        self._sub = None
        self.asked: list[str] = []

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.TASK_CREATE, self._on_create)

    async def stop(self) -> None:
        if self._sub is not None:
            await self._sub.unsubscribe()

    async def _on_create(self, message: Message) -> None:
        description = message.payload.get("description", "")
        self.asked.append(description)
        task_id = f"t{len(self.asked)}"
        await self._bus.reply(message, type=topics.TASK_CREATE_REPLY, payload={"task_id": task_id})
        if self._delay:
            await asyncio.sleep(self._delay)
        if not self._complete:
            await self._bus.publish(self._bus.new(topics.TASK_FAILED, {
                "task_id": task_id, "reason": "nothing answered", "terminal": True, "attempts": 1,
            }))
            return
        text = next((a for q, a in ANSWERS.items() if q in description), "no idea")
        await self._bus.publish(self._bus.new(topics.TASK_STEP, {
            "task_id": task_id, "step_no": 1, "phase": "act", "summary": "searched", "ok": True,
        }))
        await self._bus.publish(self._bus.new(topics.TASK_COMPLETED, {
            "task_id": task_id, "result_summary": text, "artifacts": [], "verification_ref": None,
        }))


class RunnerTestCase(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, complete: bool = True, delay: float = 0.0):
        async with Harness() as h:
            bus = h.client("benchmark")
            answerer = _Answerer(h.client("orchestration"), complete=complete, delay=delay)
            await answerer.start()
            try:
                runner = Runner(bus, config=Config(case_timeout_s=5.0, case_max_steps=7), clock=h.clock.now)
                record = await runner.run(SUITE, model="glm-test")
            finally:
                await answerer.stop()
            return record, answerer

    async def test_each_case_becomes_one_task_and_is_scored(self):
        record, answerer = await self._run()
        self.assertEqual(len(answerer.asked), 2, "the unanswerable case must not become a task")
        self.assertEqual((record.correct, record.attempted, record.skipped), (1, 2, 1))
        self.assertEqual(record.by_level(), {"1": (1, 1), "2": (0, 1)})
        self.assertEqual(record.model, "glm-test")

    async def test_the_wrong_answer_keeps_both_sides_for_the_diff(self):
        record, _ = await self._run()
        wrong = next(r for r in record.results if not r.correct and not r.skipped)
        self.assertEqual((wrong.expected, wrong.answer), ("Paris", "Berlin"))

    async def test_a_case_needing_a_file_is_skipped_not_failed(self):
        record, _ = await self._run()
        skipped = next(r for r in record.results if r.skipped)
        self.assertIn("sheet.xlsx", skipped.error)
        self.assertEqual(record.attempted, 2)

    async def test_the_answer_format_and_step_cap_reach_the_task(self):
        _record, answerer = await self._run()
        self.assertIn("FINAL ANSWER:", answerer.asked[0])
        self.assertIn("what is 2+2", answerer.asked[0])

    async def test_steps_are_counted_per_case(self):
        record, _ = await self._run()
        self.assertTrue(all(r.steps == 1 for r in record.results if not r.skipped))

    async def test_a_failed_task_is_a_wrong_answer_with_its_reason(self):
        record, _ = await self._run(complete=False)
        self.assertEqual(record.correct, 0)
        self.assertEqual(record.attempted, 2)
        self.assertIn("nothing answered", record.results[0].error)

    async def test_an_answer_that_lands_before_the_wait_is_not_missed(self):
        """The completion can arrive between the create reply and the
        wait; the watch subscribes first, so it is buffered."""
        record, _ = await self._run(delay=0.0)
        self.assertEqual(record.correct, 1)

    async def test_a_deduplicated_task_id_fails_fast_instead_of_the_full_timeout(self):
        """Observer, 2026-09-08 (GAIA deep dive): a dedupe that hands
        back an existing task_id used to make `_AnswerWatch` block the
        entire `case_timeout_s` waiting for an outcome that already
        fired to a different watcher -- 5 of 7 real GAIA cases in one
        run each cost 600s this way. `origin="benchmark"` is now exempt
        from Intake's fuzzy dedupe (test_intake.py), but this is the
        harness's own belt-and-suspenders: if a `task.create` reply ever
        carries `deduplicated_against` again, for any reason, the case
        must fail immediately and honestly, not silently burn its whole
        timeout."""
        async with Harness() as h:
            bus = h.client("benchmark")
            other = h.client("orchestration")

            async def _on_create(message: Message) -> None:
                await other.reply(message, type=topics.TASK_CREATE_REPLY, payload={
                    "task_id": "some-other-cases-task", "deduplicated_against": "some-other-cases-task",
                })

            sub = await other.subscribe(topics.TASK_CREATE, _on_create)
            try:
                runner = Runner(bus, config=Config(case_timeout_s=5.0), clock=h.clock.now)
                started = h.clock.now()
                result = await runner.run_case(SUITE.cases[0])
                elapsed = h.clock.now() - started
            finally:
                await sub.unsubscribe()
        self.assertTrue(result.skipped)
        self.assertFalse(result.correct)
        self.assertIn("some-other-cases-task", result.error)
        self.assertLess(elapsed, 1.0, "must not have waited out case_timeout_s")

    async def test_a_case_prompt_carries_the_function_schemas_when_there_are_any(self):
        async with Harness() as h:
            runner = Runner(h.client("benchmark"), clock=h.clock.now)
            case = Case(id="b1", question="book two flights", answer="[]", mode="bfcl",
                        functions='[{"name": "book"}]')
            prompt = runner.prompt(case)
            self.assertIn("Functions you may call", prompt)
            self.assertIn('{"name": "book"}', prompt)
            self.assertIn("JSON array", prompt)


class StoreTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ledger = make_ledger({"backend": "memory"}, clock=None)
        await self.ledger.start()
        self.store = RunStore(self.ledger)

    async def asyncTearDown(self) -> None:
        await self.ledger.stop()

    async def _record(self, model="glm", correct=(True, False)):
        from simorgh.benchmark.api import CaseResult, RunRecord

        record = RunRecord(suite="toy", model=model, suite_version="v1")
        for index, ok in enumerate(correct):
            record.results.append(CaseResult(case_id=f"c{index}", level="1", correct=ok,
                                             expected="x", answer="x" if ok else "y"))
        await self.store.append(record)
        return record

    async def test_an_empty_history_is_empty_not_an_error(self):
        self.assertEqual(await self.store.history(), [])
        self.assertIsNone(await self.store.latest())

    async def test_runs_come_back_oldest_first_with_their_scores(self):
        await self._record(correct=(True, False))
        await self._record(correct=(True, True))
        runs = await self.store.history()
        self.assertEqual([r.correct for r in runs], [1, 2])
        self.assertEqual((await self.store.latest()).correct, 2)

    async def test_history_filters_by_suite_and_model(self):
        await self._record(model="glm")
        await self._record(model="other")
        self.assertEqual(len(await self.store.history(model="glm")), 1)
        self.assertEqual(len(await self.store.history(suite="nope")), 0)

    async def test_the_per_case_detail_is_read_back_from_its_blob(self):
        record = await self._record(correct=(True, False))
        detail = await self.store.detail(record.run_id)
        self.assertEqual(len(detail.results), 2)
        self.assertEqual(detail.results[1].expected, "x")
        self.assertEqual(detail.results[1].answer, "y")

    async def test_an_unknown_run_id_is_none(self):
        self.assertIsNone(await self.store.detail("nope"))


class SubsystemWiringTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.kernel = Kernel(
            LoadedConfig({
                "runtime": {"data_dir": str(Path(self._tmp.name) / "data")},
                "curiosity": {"autonomy_on_boot": False},
                # An empty cache, so the gated path is really exercised:
                # a suite already downloaded needs no token, which is
                # correct behaviour and made this test pass vacuously
                # once GAIA had been fetched for real (2026-09-08).
                "benchmark": {"cache_dir": str(Path(self._tmp.name) / "cache")},
            }, None),
            secrets=EnvSecretStore({}),
        )
        await self.kernel.boot()
        self.addAsyncCleanup(self.kernel.shutdown)

    async def test_the_subsystem_boots(self) -> None:
        self.assertEqual(self.kernel._supervisor.services["benchmark"].status, "ok")  # noqa: SLF001

    async def test_a_cached_gated_suite_needs_no_token(self) -> None:
        """Downloading is what needs the token; running from a cache the
        operator already has does not."""
        from simorgh.benchmark.api import Case, Suite

        cache = Path(self._tmp.name) / "cache"
        source = datasets_mod.SOURCES["gaia"]
        rows = [{"task_id": "g1", "Question": "q", "Final answer": "a", "Level": "1"}]
        datasets_mod.save(datasets_mod.to_suite(source, rows, version="v1"), source, rows, cache)
        with mock.patch.dict("os.environ", {"HF_TOKEN": ""}, clear=False):
            suite = datasets_mod.load("gaia", cache_dir=cache)
        self.assertEqual(len(suite), 1)
        self.assertIsInstance(suite, Suite)
        self.assertIsInstance(suite.cases[0], Case)

    async def test_suites_are_listed_with_their_gating_and_scorability(self) -> None:
        reply = await self.kernel.bus.request(
            self.kernel.bus.new(topics.BENCHMARK_SUITES_REQUEST, {}), timeout=10)
        by_name = {s["name"]: s for s in reply.payload["suites"]}
        self.assertTrue(by_name["gaia"]["gated"])
        # Scorable since the container evaluator landed (2026-09-10).
        self.assertTrue(by_name["swebench-verified"]["scorable"])
        self.assertTrue(by_name["bfcl-parallel"]["scorable"])

    async def test_a_gated_suite_without_a_token_says_what_to_do(self) -> None:
        with mock.patch.dict("os.environ", {"HF_TOKEN": ""}, clear=False):
            reply = await self.kernel.bus.request(self.kernel.bus.new(
                topics.BENCHMARK_RUN_REQUEST, {"suite": "gaia", "limit": 1}), timeout=20)
        self.assertFalse(reply.payload["ok"])
        self.assertIn("HF_TOKEN", reply.payload["error"]["detail"])

    async def test_an_unscorable_suite_is_refused_rather_than_faked(self) -> None:
        """Every shipped suite is scorable today, so this uses a
        stand-in. The refusal is the point and it stays tested: a suite
        we cannot score must say so rather than report a number."""
        source = datasets_mod.SOURCES["bfcl-parallel"]
        unscorable = replace(source, scorable=False,
                             why_not_scorable="scoring it needs a container we do not have")
        with mock.patch.dict(datasets_mod.SOURCES, {"bfcl-parallel": unscorable}), \
                mock.patch.object(datasets_mod, "load", return_value=SUITE):
            reply = await self.kernel.bus.request(self.kernel.bus.new(
                topics.BENCHMARK_RUN_REQUEST, {"suite": "bfcl-parallel", "limit": 1}), timeout=20)
        self.assertFalse(reply.payload["ok"])
        self.assertEqual(reply.payload["error"]["code"], "not_scorable")
        self.assertIn("container", reply.payload["error"]["detail"])

    async def test_a_swebench_run_without_docker_is_refused_before_the_first_case(self) -> None:
        """Every case would be skipped, and a run of nothing but skips
        reads like a run that happened. Check once, refuse once."""
        from simorgh.benchmark import service as service_mod

        container_suite = replace(SUITE, cases=(
            Case(id="astropy__astropy-12907", question="fix it", answer="", suite="swebench-verified",
                 mode="swebench", data='{"image": "img", "eval_script": "true"}'),
        ))
        with mock.patch.object(datasets_mod, "load", return_value=container_suite), \
                mock.patch.object(service_mod.swebench, "available",
                                  return_value=(False, "the Docker daemon is not running")):
            reply = await self.kernel.bus.request(self.kernel.bus.new(
                topics.BENCHMARK_RUN_REQUEST, {"suite": "swebench-verified", "limit": 1}), timeout=20)
        self.assertFalse(reply.payload["ok"])
        self.assertEqual(reply.payload["error"]["code"], "needs_docker")
        self.assertIn("Docker daemon", reply.payload["error"]["detail"])

    async def test_an_unknown_suite_names_the_ones_that_exist(self) -> None:
        reply = await self.kernel.bus.request(self.kernel.bus.new(
            topics.BENCHMARK_RUN_REQUEST, {"suite": "nope", "limit": 1}), timeout=20)
        self.assertFalse(reply.payload["ok"])
        self.assertIn("gaia", reply.payload["error"]["detail"])

    async def test_history_is_empty_before_any_run(self) -> None:
        reply = await self.kernel.bus.request(self.kernel.bus.new(
            topics.BENCHMARK_HISTORY_REQUEST, {}), timeout=10)
        self.assertEqual(reply.payload["runs"], [])
        self.assertFalse(reply.payload["running"])


if __name__ == "__main__":
    unittest.main()


class StopAndBusyTestCase(unittest.IsolatedAsyncioTestCase):
    """One run at a time, and a way out of it."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.kernel = Kernel(
            LoadedConfig({
                "runtime": {"data_dir": str(Path(self._tmp.name) / "data")},
                "curiosity": {"autonomy_on_boot": False},
                "benchmark": {"cache_dir": str(Path(self._tmp.name) / "cache"), "case_timeout_s": 30.0},
            }, None),
            secrets=EnvSecretStore({}),
        )
        await self.kernel.boot()
        self.addAsyncCleanup(self.kernel.shutdown)
        self._service = self.kernel._supervisor.services["benchmark"].service  # noqa: SLF001

    async def _start_a_run(self) -> dict:
        """A suite whose cases never get answered, so the run stays in
        flight for the test to act on."""
        slow = Suite(name="toy", version="v1", cases=tuple(
            Case(id=f"c{i}", question=f"question {i}", answer="x", level="1", suite="toy") for i in range(5)
        ))
        self._patch = mock.patch.object(datasets_mod, "load", return_value=slow)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        mock.patch.dict(datasets_mod.SOURCES, {"toy": datasets_mod.Source(
            name="toy", dataset="local/toy", config="default", split="test")}).start()
        reply = await self.kernel.bus.request(self.kernel.bus.new(
            topics.BENCHMARK_RUN_REQUEST, {"suite": "toy", "limit": 5}), timeout=15)
        for _ in range(200):
            if self._service._running.get("index"):  # noqa: SLF001
                break
            await asyncio.sleep(0.01)
        return reply.payload

    async def test_a_second_run_is_refused_with_progress_and_a_way_out(self) -> None:
        await self._start_a_run()
        reply = await self.kernel.bus.request(self.kernel.bus.new(
            topics.BENCHMARK_RUN_REQUEST, {"suite": "toy", "limit": 5}), timeout=15)
        self.assertFalse(reply.payload["ok"])
        detail = reply.payload["error"]["detail"]
        self.assertEqual(reply.payload["error"]["code"], "already_running")
        self.assertIn("of 5", detail)
        self.assertIn("benchmark stop", detail)

    async def test_stop_ends_it_and_keeps_the_partial_result(self) -> None:
        await self._start_a_run()
        reply = await self.kernel.bus.request(self.kernel.bus.new(
            topics.BENCHMARK_STOP_REQUEST, {}), timeout=30)
        self.assertTrue(reply.payload["stopped"])
        self.assertIn("partial result is recorded", reply.payload["detail"])
        store = RunStore(self.kernel.ledger, clock=self.kernel._clock.now)  # noqa: SLF001
        record = await store.latest(suite="toy")
        self.assertIsNotNone(record, "a stopped run must still be recorded")
        self.assertTrue(record.partial)

    async def test_stopping_nothing_says_so(self) -> None:
        reply = await self.kernel.bus.request(self.kernel.bus.new(
            topics.BENCHMARK_STOP_REQUEST, {}), timeout=15)
        self.assertFalse(reply.payload["stopped"])
        self.assertIn("no benchmark run", reply.payload["detail"])

    async def test_a_run_may_start_again_after_a_stop(self) -> None:
        await self._start_a_run()
        await self.kernel.bus.request(self.kernel.bus.new(topics.BENCHMARK_STOP_REQUEST, {}), timeout=30)
        reply = await self.kernel.bus.request(self.kernel.bus.new(
            topics.BENCHMARK_RUN_REQUEST, {"suite": "toy", "limit": 2}), timeout=15)
        self.assertTrue(reply.payload["ok"], reply.payload)


class BlockedAnswersAreStillScoredTestCase(unittest.IsolatedAsyncioTestCase):
    """A task our own pipeline blocked still carries the answer it had.
    Scoring it is what tells us whether our verifier is throwing away
    right answers -- three of seven GAIA cases were blocked, and the
    harness recorded nothing about what they said (2026-09-08)."""

    async def _run_with_block(self, text: str, reason: str = "verification failed after max revisions"):
        async with Harness() as h:
            other = h.client("orchestration")
            sub = None

            async def _on_create(message: Message) -> None:
                await other.reply(message, type=topics.TASK_CREATE_REPLY, payload={"task_id": "tb"})
                payload = {"task_id": "tb", "reason": reason}
                if text:
                    payload["result_summary"] = text
                await other.publish(other.new(topics.TASK_BLOCKED, payload))

            sub = await other.subscribe(topics.TASK_CREATE, _on_create)
            try:
                runner = Runner(h.client("benchmark"), config=Config(case_timeout_s=5.0), clock=h.clock.now)
                one = Suite(name="toy", version="v1", cases=(
                    Case(id="c1", question="capital of France", answer="Paris", level="1", suite="toy"),
                ))
                return await runner.run(one, model="m")
            finally:
                await sub.unsubscribe()

    async def test_a_right_answer_our_verifier_rejected_is_scored_and_flagged(self):
        record = await self._run_with_block("FINAL ANSWER: Paris")
        [result] = record.results
        self.assertTrue(result.correct, "the answer was right; the verifier was not")
        self.assertIn("verification failed", result.blocked_by)
        self.assertEqual(record.blocked, 1)
        self.assertEqual(record.blocked_but_correct, 1)
        self.assertEqual(record.correct, 1)

    async def test_a_wrong_blocked_answer_is_blocked_but_not_counted_right(self):
        record = await self._run_with_block("FINAL ANSWER: Berlin")
        self.assertEqual((record.correct, record.blocked, record.blocked_but_correct), (0, 1, 0))
        self.assertEqual(record.results[0].answer, "Berlin")

    async def test_a_block_with_no_answer_at_all_is_just_a_miss(self):
        record = await self._run_with_block("", reason="step budget exhausted before the task was finished")
        [result] = record.results
        self.assertFalse(result.correct)
        self.assertEqual(result.blocked_by, "")
        self.assertIn("step budget", result.error)
        self.assertEqual(record.blocked, 0)

    async def test_the_counts_reach_the_payload(self):
        record = await self._run_with_block("FINAL ANSWER: Paris")
        payload = record.to_payload(with_cases=False)
        self.assertEqual(payload["blocked"], 1)
        self.assertEqual(payload["blocked_but_correct"], 1)
