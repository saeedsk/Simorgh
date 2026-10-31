"""A background task ends as a small card, once (the creator, 2026-10-30:
"make the sim sub task activities presentation pleasant and nice and clean
and informative").

Before: every patch left its whole fifteen-line handover under its corner,
a project printed the planner's raw JSON, and a blocked task printed its
corner twice (the Worker's `task.blocked`, then Planning's own). Now: a
headline of facts, two lines of gist, and `tasks <id>` for the rest.
"""

from __future__ import annotations

import json
import os
import unittest
import unittest.mock

from simorgh.contracts import topics
from simorgh.interface import panel, render
from simorgh.interface.activity import TaskRecord

from .test_activity import TestTheServiceNarratesAutonomousWork, _created

HANDOVER = ("I could not complete this task, and I will not pretend otherwise. **What was asked:** create "
            "`simorgh/growth/calibration.py` exposing `record()`. **What actually happened:** no code was "
            "written and nothing was committed. " + "More detail follows here. " * 30)
PLAN = json.dumps({"nodes": [{"id": "n1", "kind": "research"}, {"id": "n2", "kind": "patch"},
                             {"id": "n3", "kind": "patch"}, {"id": "n4", "kind": "wait"}]})


def _at(columns: int):
    return unittest.mock.patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 24)))


class TheCard(unittest.TestCase):
    def test_a_long_answer_is_a_short_gist_and_a_pointer(self):
        record = TaskRecord(task_id="926ba8d4abcdef", kind="patch", status="blocked", steps=18)
        with _at(100):
            card = panel.tree_digest(record, elapsed=120.0, detail=HANDOVER).splitlines()
        self.assertIn("‖ blocked · 2.0m · 18 steps", card[0])
        self.assertLessEqual(len(card), 1 + panel.GIST_LINES + 1)
        self.assertNotIn("**", "\n".join(card), "markdown marks are not shown raw")
        self.assertNotIn("`", "\n".join(card))
        self.assertIn("tasks 926ba8d4abcd", card[-1])

    def test_a_short_answer_is_shown_whole_with_no_pointer(self):
        card = panel.tree_digest(TaskRecord(task_id="t1", status="completed", steps=1), elapsed=2.0,
                                 detail="three exports")
        self.assertIn("three exports", card)
        self.assertNotIn("full report", card)

    def test_a_plan_is_a_line_not_json(self):
        card = panel.tree_digest(TaskRecord(task_id="p1", kind="project", status="completed"), elapsed=15.0,
                                 detail=PLAN)
        self.assertIn("planned 4 steps: 2 patches, 1 research, 1 wait", card)
        self.assertNotIn("{", card)

    def test_no_line_overruns_any_width(self):
        record = TaskRecord(task_id="926ba8d4abcdef", kind="patch", status="blocked", steps=18)
        for columns in (60, 80, 120, 200):   # 60 is the interface's floor (`render._MIN_WIDTH`)
            with _at(columns):
                for line in panel.tree_digest(record, elapsed=61.0, detail=HANDOVER).splitlines():
                    self.assertLessEqual(len(line), columns + 2, f"{columns}: {line!r}")


class OneEndingPerTask(TestTheServiceNarratesAutonomousWork):
    async def test_a_blocked_task_republished_by_planning_ends_once(self):
        await self._emit(topics.TASK_CREATED, {**_created("auto-9"), "depends_on": [], "mode": "execute",
                                               "risk": "low"})
        await self._emit(topics.TASK_STARTED, {"task_id": "auto-9", "worker_id": "w1"})
        await self._emit(topics.TASK_BLOCKED, {"task_id": "auto-9", "reason": HANDOVER})
        await self._emit(topics.TASK_BLOCKED, {"task_id": "auto-9",
                                               "reason": "verification failed after max revisions"})
        import re

        out = re.sub(r"\x1b\[[0-9;]*m", "", self._out())      # colour off: the words are the subject
        self.assertEqual(out.count("‖ blocked"), 1)
        self.assertIn("tasks auto-9", out)
        self.assertNotIn("max revisions", out)

    async def test_a_queued_line_names_the_kind(self):
        await self._emit(topics.TASK_CREATED, {**_created("auto-10", kind="patch"), "depends_on": [],
                                               "mode": "execute", "risk": "low"})
        self.assertIn("queued  patch · ", self._out())


class TheReport(unittest.TestCase):
    def test_it_reads_planning_records_and_shows_the_whole_answer(self):
        events = [
            ("created", {"kind": "patch", "origin": "human", "description": "build a page for 95120"}),
            ("task.step", {"tool": "search_listings", "ok": True, "summary": "8 listings", "cost_usd": 0.01}),
            ("task.step", {"tool": "worktree_land", "ok": False, "summary": "nothing to land"}),
            ("task.completed", {"result_summary": HANDOVER}),
        ]
        with _at(100):
            page = render.task_report("ca3e8e68cc75", events, enabled=False)
        self.assertIn("patch · human · completed · 2 steps · $0.01", page)
        self.assertIn("build a page for 95120", page)
        self.assertIn("✓ search_listings", page)
        self.assertIn("✗ worktree_land", page)
        self.assertIn("More detail follows here.", page.splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
