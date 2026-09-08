"""Full visibility into what Sim is doing.

The creator, 2026-09-07: "these thing were happening behind the scene and
I was not aware of them, i want full visibility ... these thing should
tell me what they are doing, what is in queue and what is the topic of
research or skill."

They could not see it because `_on_task_event` returned early for any
task not in `_pending_turns` or `_watched_tasks`, so every autonomous
task -- nearly all of them -- ran silently. And even where narration did
fire, a start could only print an id: the topic lives in `task.created`,
which nobody held on to.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.interface.activity import TaskBook, finished_line, footer, started_line, step_line
from simorgh.interface.config import Config as InterfaceConfig
from simorgh.interface.service import Service
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


def _created(task_id="t1", **kw) -> dict:
    return {
        "task_id": task_id, "kind": kw.get("kind", "research"),
        "origin": kw.get("origin", "curiosity"),
        "description": kw.get("description", "What does the memory package export?"),
        "subject": kw.get("subject"),
    }


class TestTheBook(unittest.TestCase):
    def test_a_task_knows_its_topic_not_just_its_id(self):
        book = TaskBook()
        record = book.on_created(_created())
        self.assertIn("memory package", record.topic)

    def test_a_subject_leads_the_topic(self):
        """`research src/memory/__init__.py` says more than the first few
        words of the question."""
        book = TaskBook()
        record = book.on_created(_created(subject="src/memory/__init__.py"))
        self.assertTrue(record.topic.startswith("src/memory/__init__.py"))

    def test_a_subject_already_in_the_description_is_not_repeated(self):
        book = TaskBook()
        record = book.on_created(_created(
            description="src/x.py: tidy the exports", subject="src/x.py",
        ))
        self.assertEqual(record.topic.count("src/x.py"), 1)

    def test_a_task_never_seen_created_still_gets_a_row(self):
        """A task carried over from a previous run should degrade to an
        id and a status, never to silence."""
        book = TaskBook()
        record = book.get("unknown-1")
        self.assertEqual(record.task_id, "unknown-1")
        self.assertIn("no description", record.topic)

    def test_running_and_queued_are_reported_separately(self):
        book = TaskBook()
        book.on_created(_created("a"))
        book.on_created(_created("b"))
        book.on_started("a", now=100.0)
        self.assertEqual([t.task_id for t in book.running()], ["a"])
        self.assertEqual([t.task_id for t in book.queued()], ["b"])

    def test_a_finished_task_is_neither_running_nor_queued(self):
        book = TaskBook()
        book.on_created(_created("a"))
        book.on_started("a", now=1.0)
        book.on_finished("a", "completed")
        self.assertEqual(book.running(), [])
        self.assertEqual(book.queued(), [])

    def test_the_book_does_not_grow_without_bound(self):
        book = TaskBook()
        for i in range(700):
            book.on_created(_created(f"t{i}"))
        self.assertLessEqual(len(book.tasks), 500)
        self.assertIn("t699", book.tasks)  # the newest survive


class TestTheLines(unittest.TestCase):
    def setUp(self) -> None:
        self.book = TaskBook()
        self.record = self.book.on_created(_created(kind="research", origin="curiosity"))

    def test_a_start_names_the_kind_the_origin_and_the_topic(self):
        line = started_line(self.record, unicode=False)
        for fragment in ("research", "curiosity", "memory package", self.record.task_id[:8]):
            self.assertIn(fragment, line)

    def test_the_origin_distinguishes_sims_own_idea_from_a_request(self):
        """"Sim decided to do this" and "you asked for this" were
        indistinguishable before."""
        mine = self.book.on_created(_created("t2", origin="human"))
        self.assertIn("human", started_line(mine, unicode=False))
        self.assertIn("curiosity", started_line(self.record, unicode=False))

    def test_a_step_says_which_tool_and_on_what(self):
        line = step_line(self.record, tool="search_code", summary="simorgh/memory", ok=True, unicode=False)
        self.assertIn("search_code", line)
        self.assertIn("simorgh/memory", line)

    def test_a_long_step_is_truncated_rather_than_flooding_the_screen(self):
        line = step_line(self.record, tool="read_file", summary="x" * 500, ok=True, unicode=False)
        self.assertLess(len(line), 130)

    def test_an_outcome_reports_status_duration_and_topic(self):
        self.book.on_finished(self.record.task_id, "completed")
        line = finished_line(self.record, elapsed=12.0, detail="found three exports", unicode=False)
        self.assertIn("completed", line)
        self.assertIn("12s", line)
        self.assertIn("memory package", line)


class TestTheFooter(unittest.TestCase):
    def test_idle_says_idle(self):
        self.assertEqual(footer(TaskBook(), now=0.0), "idle")

    def test_idle_with_a_backlog_says_how_much_is_waiting(self):
        book = TaskBook()
        book.on_created(_created("a"))
        book.on_created(_created("b"))
        self.assertIn("2 queued", footer(book, now=0.0))

    def test_running_work_shows_what_and_for_how_long(self):
        book = TaskBook()
        book.on_created(_created("a", kind="patch", description="tighten the retry loop"))
        book.on_started("a", now=100.0)
        line = footer(book, now=112.0)
        self.assertIn("patch", line)
        self.assertIn("tighten the retry loop", line)
        self.assertIn("12s", line)

    def test_the_queue_is_visible_while_work_runs(self):
        book = TaskBook()
        book.on_created(_created("a"))
        book.on_created(_created("b"))
        book.on_started("a", now=0.0)
        self.assertIn("1 queued", footer(book, now=1.0))


class TestTheServiceNarratesAutonomousWork(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="interface", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.other = make_client(backend, source="planning", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()

        self.service = Service(InterfaceConfig(), run_repl=False, http_enabled=False)
        await self.service.start(Context(
            name="interface", instance_id="", run_id="t", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name),
        ))
        self.printed: list[str] = []
        self.service._out = self.printed.append  # noqa: SLF001

    async def asyncTearDown(self) -> None:
        await self.service.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _emit(self, type_: str, payload: dict) -> None:
        await self.other.publish(self.other.new(type_, payload))
        for _ in range(20):
            await asyncio.sleep(0)

    def _out(self) -> str:
        return "\n".join(self.printed)

    async def test_a_curiosity_task_announces_itself_with_its_topic(self):
        await self._emit(topics.TASK_CREATED, {
            **_created("auto-1", description="What does src/memory export?"),
            "depends_on": [], "mode": "execute", "risk": "low",
        })
        await self._emit(topics.TASK_STARTED, {"task_id": "auto-1", "worker_id": "w1"})
        out = self._out()
        self.assertIn("research", out)
        self.assertIn("curiosity", out)
        self.assertIn("What does src/memory export?", out)

    async def test_its_steps_are_narrated(self):
        await self._emit(topics.TASK_CREATED, {
            **_created("auto-2"), "depends_on": [], "mode": "execute", "risk": "low",
        })
        await self._emit(topics.TASK_STARTED, {"task_id": "auto-2", "worker_id": "w1"})
        await self._emit(topics.TASK_STEP, {
            "task_id": "auto-2", "step_no": 1, "phase": "act",
            "summary": "simorgh/memory", "tool": "search_code", "ok": True,
        })
        self.assertIn("search_code", self._out())

    async def test_its_outcome_is_narrated(self):
        await self._emit(topics.TASK_CREATED, {
            **_created("auto-3"), "depends_on": [], "mode": "execute", "risk": "low",
        })
        await self._emit(topics.TASK_STARTED, {"task_id": "auto-3", "worker_id": "w1"})
        await self._emit(topics.TASK_COMPLETED, {
            "task_id": "auto-3", "result_summary": "three exports", "artifacts": [],
            "verification_ref": None,
        })
        out = self._out()
        self.assertIn("completed", out)
        self.assertIn("three exports", out)

    async def test_the_footer_reports_what_is_running(self):
        await self._emit(topics.TASK_CREATED, {
            **_created("auto-4", kind="patch", description="tighten the retry loop"),
            "depends_on": [], "mode": "execute", "risk": "low",
        })
        await self._emit(topics.TASK_STARTED, {"task_id": "auto-4", "worker_id": "w1"})
        self.assertIn("tighten the retry loop", self.service._footer)  # noqa: SLF001

    async def test_turning_it_off_restores_the_old_silence(self):
        self.service.config = InterfaceConfig(narrate_autonomous=False)
        await self._emit(topics.TASK_CREATED, {
            **_created("auto-5"), "depends_on": [], "mode": "execute", "risk": "low",
        })
        await self._emit(topics.TASK_STARTED, {"task_id": "auto-5", "worker_id": "w1"})
        self.assertEqual(self.printed, [])


if __name__ == "__main__":
    unittest.main()
