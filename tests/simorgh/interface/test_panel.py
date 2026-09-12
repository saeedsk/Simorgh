"""The Claude-Code-shaped screen (`interface/panel.py`), without a terminal."""

from __future__ import annotations

import unittest

from simorgh.interface import panel
from simorgh.interface.activity import TaskBook, TaskRecord


def _running(task_id="t1", *, kind="patch", topic="tighten the retry loop", started=0.0, steps=0) -> TaskBook:
    book = TaskBook()
    book.on_created({"task_id": task_id, "kind": kind, "origin": "human", "description": topic})
    book.on_started(task_id, now=started)
    for _ in range(steps):
        book.on_step(task_id, now=started + 1)
    return book


class BreathingTestCase(unittest.TestCase):
    def test_the_creators_own_words_are_in_the_rotation(self):
        for word in ("Thinkering", "Osmosing", "Snargling", "Dive-deeping"):
            self.assertIn(word, panel.BREATH_WORDS)

    def test_a_word_is_stable_within_a_rotation_and_changes_across_one(self):
        a = panel.breath_word("task-1", 0.0)
        b = panel.breath_word("task-1", panel.BREATH_ROTATE_S - 0.1)
        c = panel.breath_word("task-1", panel.BREATH_ROTATE_S + 0.1)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_different_tasks_breathe_different_words(self):
        words = {panel.breath_word(f"task-{n}", 0.0) for n in range(20)}
        self.assertGreater(len(words), 3)

    def test_the_shade_rises_and_falls_within_one_period(self):
        period = panel.BREATH_PERIOD_S
        self.assertEqual(panel.breath_shade(0.0), 0)
        self.assertEqual(panel.breath_shade(period / 2), panel.BREATH_SHADES - 1)
        self.assertEqual(panel.breath_shade(period), 0)
        self.assertTrue(panel.breath_class(1.0).startswith("class:sim.breath."))


class TreeTestCase(unittest.TestCase):
    def test_the_root_names_kind_origin_and_topic(self):
        record = TaskRecord(task_id="abcdef123456", kind="patch", origin="human", description="add a docstring")
        line = panel.tree_start(record)
        self.assertTrue(line.startswith("⏺ "))
        for fragment in ("patch", "human", "add a docstring", "[abcdef12]"):
            self.assertIn(fragment, line)

    def test_a_step_is_a_branch_with_its_outcome_and_timing_at_the_right(self):
        line = panel.tree_step(tool="read_file", head="simorgh/x.py", ok=True, took=0.31, width=60)
        self.assertTrue(line.startswith("  ⏺ read_file(simorgh/x.py)"), line)
        self.assertTrue(line.endswith("✓ 0.3s"))
        self.assertEqual(len(line), 60)

    def test_a_failed_step_is_marked_and_a_long_one_is_cut(self):
        line = panel.tree_step(tool="run_tests", head="x" * 200, ok=False, took=42.0, width=60)
        self.assertLessEqual(len(line), 60)
        self.assertTrue(line.endswith("✗ 42s"))
        self.assertIn("…", line)

    def test_ascii_when_unicode_is_off(self):
        line = panel.tree_step(tool="read_file", head="a.py", ok=True, took=1.0, unicode=False)
        self.assertTrue(line.startswith("  * "))
        self.assertTrue(line.endswith("ok 1.0s"))

    def test_notes_sit_inside_the_rail(self):
        self.assertEqual(panel.tree_note(["+x", "-y"]), ["    ⎿  +x", "       -y"])

    def test_the_end_closes_the_tree_with_the_outcome_and_duration(self):
        record = TaskRecord(task_id="t1", status="completed")
        line = panel.tree_end(record, elapsed=61.0)
        self.assertIn("⎿  ✅ completed in 61s", line)
        blocked = panel.tree_end(TaskRecord(task_id="t1", status="blocked"), elapsed=3.0, detail="no budget")
        self.assertIn("⏸ blocked in 3.0s -- no budget", blocked)


class SparkAndWaveTestCase(unittest.TestCase):
    def test_the_spark_opens_and_closes_over_time(self) -> None:
        frames = [panel.spark(t * panel.SPARK_FRAME_S) for t in range(len(panel.SPARK_FRAMES))]
        self.assertEqual(frames, list(panel.SPARK_FRAMES))
        self.assertEqual(panel.spark(0.0, unicode=False), "*")

    def test_each_letter_breathes_a_beat_after_the_one_to_its_left(self) -> None:
        word = panel.breathing_word("Shimmying", 0.0)
        self.assertEqual("".join(ch for _c, ch in word), "Shimmying…")
        shades = [int(cls.rsplit(".", 1)[1]) for cls, _ch in word]
        self.assertTrue(all(0 <= s < panel.BREATH_SHADES for s in shades))
        # The wave moves: a beat later the same letter has the shade its right-hand neighbour had.
        later = panel.breathing_word("Shimmying", panel.WAVE_SPREAD * panel.WAVE_PERIOD_S)
        later_shades = [int(cls.rsplit(".", 1)[1]) for cls, _ch in later]
        self.assertEqual(later_shades[1:], shades[:-1])


class BottomRowsTestCase(unittest.TestCase):
    def test_idle_with_nothing_queued_is_idle_plus_the_status_row(self):
        rows = panel.footer_rows(TaskBook(), now=0.0, auto="on")
        self.assertEqual(panel.plain(rows), "idle\n⏵⏵ auto on")

    def test_a_running_task_breathes_above_the_prompt_and_is_listed_plainly_below(self):
        book = _running(started=0.0, steps=2)
        live = panel.live_rows(book, now=12.0)
        first = live[0]
        self.assertTrue(first[0][0].startswith("class:sim.breath."))  # the spark breathes
        self.assertIn(first[0][1].strip(), panel.SPARK_FRAMES)
        letters = [frag for frag in first[1:] if frag[0].startswith("class:sim.breath.")]
        self.assertIn("".join(ch for _cls, ch in letters).rstrip("…"), panel.BREATH_WORDS)
        self.assertIn("patch · tighten the retry loop · 12s · 2 steps", panel.plain(live))
        ribbon = panel.plain(panel.footer_rows(book, now=12.0, auto="off", posture="guarded", model="GLM-5.3-Flash"))
        self.assertIn("⏺ patch · tighten the retry loop · 12s", ribbon)
        self.assertNotIn("…", ribbon.split("\n")[0], "no breathing in the ribbon")
        self.assertIn("auto off · guarded · GLM-5.3-Flash", ribbon)

    def test_a_tool_call_in_flight_is_drawn_in_place_above_the_breathing_line(self):
        # The creator, 2026-09-12: "a dynamic section showing current
        # activity, process, shell in nested format which ... gets
        # updated in place", above the breathing bullet, above the prompt.
        book = _running()
        book.on_step("t1", now=0.0, phase="act", verb="Running", in_flight=True, tool="run_shell",
                     detail="python -m pytest tests/simorgh/interface -q")
        rows = panel.live_rows(book, now=3.0)
        text = panel.plain(rows)
        self.assertTrue(text.startswith("⏺ run_shell(python -m pytest tests/simorgh/interface -q)"), text)
        self.assertIn("⎿  running… 3s", text)
        self.assertEqual("".join(ch for cls, ch in rows[2] if cls.startswith("class:sim.breath.")).strip(),
                         f"{panel.spark(3.0)} Running…")
        book.on_step("t1", now=4.0, in_flight=False)  # it landed: the block goes, the breathing stays
        text = panel.plain(panel.live_rows(book, now=5.0))
        self.assertNotIn("run_shell(", text)
        self.assertIn(text[0], panel.SPARK_FRAMES, text)

    def test_idle_shows_nothing_live_but_what_just_finished(self):
        self.assertEqual(panel.live_rows(TaskBook(), now=0.0), [])
        row = panel.live_rows(TaskBook(), now=0.0, footer_text="⏺ Thinking...  [4s]")[0]
        self.assertIn(row[0][1].strip(), panel.SPARK_FRAMES, "the one-line status breathes too")
        self.assertEqual("".join(ch for cls, ch in row if cls.startswith("class:sim.breath."))[2:], "Thinking…")
        self.assertIn("[4s]", panel.plain([row]))
        self.assertEqual(panel.plain(panel.live_rows(TaskBook(), now=0.0, footer_text="no verb here")), "no verb here")
        done = panel.plain(panel.live_rows(TaskBook(), now=0.0, last_done=("Baked", 61.0, "04:33")))
        self.assertEqual(done, "✻ Baked for 61s · done 04:33")

    def test_the_queue_names_what_waits(self):
        book = _running()
        book.on_created({"task_id": "q1", "kind": "research", "origin": "curiosity", "description": "what does memory export"})
        book.on_created({"task_id": "q2", "kind": "plan", "origin": "human", "description": "web access"})
        book.on_created({"task_id": "q3", "kind": "plan", "origin": "human", "description": "third"})
        # Widths follow the real terminal now, so assert the shape rather
        # than an exact string a narrow window would legitimately shorten.
        text = panel.plain(panel.footer_rows(book, now=1.0, auto="on"))
        self.assertIn("↳ 3 queued:", text)
        self.assertIn("web access", text)
        self.assertIn("(+1)", text)
        self.assertRegex(text, r"what does memory ex")

    def test_flatten_puts_newlines_between_rows_only(self):
        flat = panel.flatten([[("a", "x")], [("b", "y")]])
        self.assertEqual(flat, [("a", "x"), ("", "\n"), ("b", "y")])

    def test_budget_summary(self):
        self.assertEqual(panel.budget_summary({"together": {"calls": 12, "max_calls": 200}}), "together 12/200")
        self.assertEqual(panel.budget_summary({"together": {"calls": 3, "max_calls": None}}), "together 3 calls")
        self.assertEqual(panel.budget_summary({"together": {"calls": 9, "exhausted": True}}), "together budget exhausted")
        self.assertEqual(panel.budget_summary({}), "")


class StepTimingTestCase(unittest.TestCase):
    def test_a_finished_step_is_timed_from_the_previous_event(self):
        book = _running(started=10.0)
        self.assertAlmostEqual(book.step_took("t1", now=10.4), 0.4)
        book.on_step("t1", now=10.4)
        self.assertAlmostEqual(book.step_took("t1", now=12.4), 2.0)

    def test_an_in_flight_step_does_not_count_or_move_the_clock(self):
        book = _running(started=10.0)
        book.on_step("t1", phase="gather", verb="Thinking", in_flight=True)
        record = book.get("t1")
        self.assertEqual(record.steps, 0)
        self.assertEqual(record.phase, "gather")
        self.assertEqual(book.step_took("t1", now=11.0), 1.0)


if __name__ == "__main__":
    unittest.main()
