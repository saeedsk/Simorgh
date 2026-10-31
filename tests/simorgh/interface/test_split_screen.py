"""The split screen: conversation left, a column of boxes right (the creator,
2026-10-30: "a right side box ... first box cpu usage, gpu history, cpu
core usage history; second memory and cpu in numbers; then parallel agents
... a key and tab to switch between these windows and make them full size").

The boxes are plain data (`sidepanel.py`), tested without a terminal; the
screen itself (`splitscreen.py`) is driven end to end through a pipe and a
fake 120x40 terminal.
"""

from __future__ import annotations

import asyncio
import io
import re
import sys
import unittest
from types import SimpleNamespace

from simorgh.interface import sidepanel
from simorgh.interface.config import Config
from simorgh.interface.sidepanel import (AgentFeeds, MemoryBox, ProcessorBox, SystemSampler, human_bytes,
                                         spark)
from simorgh.interface.splitscreen import Panes, Transcript


def _text(fragments) -> str:
    return "".join(t for _s, t in fragments)


class _FakePsutil:
    """Enough of psutil for the sampler, with readings the test chose."""

    def __init__(self, cores=(10.0, 90.0, 50.0, 30.0)):
        self.cores = list(cores)

    def cpu_percent(self, percpu=False):
        return list(self.cores) if percpu else sum(self.cores) / len(self.cores)

    def virtual_memory(self):
        return SimpleNamespace(total=32 * 1024 ** 3, available=8 * 1024 ** 3)

    def swap_memory(self):
        return SimpleNamespace(used=512 * 1024 ** 2)

    def Process(self, pid):  # noqa: N802 -- psutil's own name
        return SimpleNamespace(cpu_percent=lambda: 3.0, memory_info=lambda: SimpleNamespace(rss=400 * 1024 ** 2))


def _ioreg(text):
    return lambda *a, **k: SimpleNamespace(stdout=text)


IOREG = '"PerformanceStatistics" = {"Device Utilization %"=42,"Renderer Utilization %"=40}\n"gpu-core-count" = 12'


class Readings(unittest.TestCase):
    def test_spark_fills_from_the_right_and_scales_to_the_top(self):
        self.assertEqual(spark([], width=4), "    ")
        self.assertEqual(spark([0, 100], width=4), "  ▁█")
        self.assertEqual(len(spark(range(200), width=10, top=200)), 10)

    def test_human_bytes(self):
        self.assertEqual(human_bytes(512), "512B")
        self.assertEqual(human_bytes(3 * 1024 ** 3), "3.0GB")

    def test_the_sampler_keeps_a_history_per_core_and_for_the_gpu(self):
        sampler = SystemSampler(psutil_module=_FakePsutil(), run=_ioreg(IOREG), platform="darwin", gpu_every_s=0)
        for _ in range(3):
            sampler.sample()
        r = sampler.readings
        self.assertEqual(len(r.cores), 4)
        self.assertEqual(list(r.cores[1]), [90.0, 90.0, 90.0])
        self.assertEqual(r.cpu[-1], 45.0)
        self.assertEqual((list(r.gpu), r.gpu_cores), ([42.0, 42.0, 42.0], 12))
        self.assertEqual(r.mem_used, 24 * 1024 ** 3)

    def test_a_missing_source_says_so_rather_than_showing_zeros(self):
        sampler = SystemSampler(psutil_module=None, run=_ioreg(""), platform="linux")
        sampler.readings.missing.setdefault("cpu", "psutil is not installed (pip install psutil)")
        sampler.sample()
        text = _text(ProcessorBox(sampler).render(40, 10))
        self.assertIn("psutil is not installed", text)
        self.assertIn("macOS only", text)
        self.assertNotIn("%", text)


class Boxes(unittest.TestCase):
    def setUp(self):
        self.sampler = SystemSampler(psutil_module=_FakePsutil(), run=_ioreg(IOREG), platform="darwin",
                                     gpu_every_s=0)
        self.sampler.sample()

    def test_the_processor_box_shows_cpu_each_core_and_the_gpu(self):
        text = _text(ProcessorBox(self.sampler).render(40, 10))
        for label in ("cpu", "c0", "c3", "gpu", "12 cores", "90%"):
            self.assertIn(label, text)

    def test_a_short_box_says_how_many_cores_are_hidden(self):
        text = _text(ProcessorBox(self.sampler).render(40, 5))
        self.assertIn("+2 more cores", text)

    def test_a_hot_core_is_drawn_hot(self):
        styles = {s for s, t in ProcessorBox(self.sampler).render(40, 10) if "90%" in t}
        self.assertEqual(styles, {"class:side.value"})
        self.assertEqual(sidepanel.heat(90), "class:side.hot")

    def test_the_memory_box_is_numbers(self):
        text = _text(MemoryBox(self.sampler).render(40, 8))
        for part in ("RAM", "75%", "24.0GB of 32.0GB", "swap", "512MB", "sim", "400MB"):
            self.assertIn(part, text)

    def test_no_box_line_overruns_its_width(self):
        for box in (ProcessorBox(self.sampler), MemoryBox(self.sampler)):
            for line in _text(box.render(40, 10)).splitlines():
                self.assertLessEqual(len(line), 40, line)


class Agents(unittest.TestCase):
    def test_a_box_per_running_agent_with_its_newest_lines(self):
        clock = [0.0]
        feeds = AgentFeeds(clock=lambda: clock[0], linger_s=5.0)
        feeds.started("t1", "research · notify")
        for i in range(10):
            feeds.step("t1", tool="read_file", summary=f"file {i}", ok=True)
        feeds.step("t1", tool="run_shell", summary="pytest -q", ok=None)
        (box,) = feeds.boxes()
        text = _text(box.render(40, 4))
        self.assertIn("file 9", text)
        self.assertNotIn("file 0", text, "the newest lines, not the oldest")
        self.assertIn("⏺ run_shell: pytest -q", text)

    def test_a_finished_agent_lingers_then_leaves(self):
        clock = [0.0]
        feeds = AgentFeeds(clock=lambda: clock[0], linger_s=5.0)
        feeds.started("t1", "patch · imap")
        feeds.ended("t1", "completed", "reconnects after idle")
        self.assertIn("✅ completed", _text(feeds.boxes()[0].render(40, 4)))
        clock[0] = 10.0
        self.assertEqual(feeds.boxes(), [])


class PaneFocus(unittest.TestCase):
    def test_shift_tab_walks_conversation_then_each_box(self):
        panes = Panes()
        seen = []
        for _ in range(4):
            panes.next(3)
            seen.append(panes.focus)
        self.assertEqual(seen, [1, 2, 3, 0])

    def test_full_size_follows_focus_and_restores(self):
        panes = Panes()
        panes.next(2)
        panes.toggle_full()
        self.assertEqual(panes.maximised, 1)
        panes.next(2)
        self.assertEqual(panes.maximised, 2, "moving focus while full size shows the next pane full size")
        panes.restore()
        self.assertIsNone(panes.maximised)

    def test_a_box_that_went_away_is_never_focused(self):
        panes = Panes()
        panes.focus, panes.maximised = 4, 4
        panes.clamp(2)
        self.assertEqual((panes.focus, panes.maximised), (2, None))


class TheTranscript(unittest.TestCase):
    def test_it_keeps_lines_from_any_writer_and_follows_the_end(self):
        changes = []
        t = Transcript(limit=5, on_change=lambda: changes.append(1))
        t.write("one\ntwo\nthr")
        t.write("ee\n")
        print("four", file=t)
        self.assertEqual(t.lines(), ["one", "two", "three", "four"])
        self.assertTrue(changes)
        for i in range(10):
            t.write(f"line {i}\n")
        self.assertEqual(len(t.lines()), 5, "bounded")
        lines, last = t.tail(rows=10)
        self.assertEqual(lines[last], "line 9")

    def test_scrolling_up_ends_the_view_earlier(self):
        t = Transcript()
        for i in range(50):
            t.write(f"line {i}\n")
        t.scroll = 10
        lines, last = t.tail(rows=5)
        self.assertEqual(lines[last], "line 39")


class TheLayoutSetting(unittest.TestCase):
    def test_inline_by_default_split_by_setting(self):
        self.assertEqual(Config().layout, "inline")
        self.assertEqual(Config.from_mapping({"layout": "split", "side_width": 50}).side_width, 50)


class EndToEnd(unittest.IsolatedAsyncioTestCase):
    async def test_the_screen_draws_the_boxes_takes_a_line_and_switches_panes(self):
        try:
            from prompt_toolkit.data_structures import Size
            from prompt_toolkit.input import create_pipe_input
            from prompt_toolkit.output.vt100 import Vt100_Output
        except ImportError:
            self.skipTest("prompt_toolkit is not installed")
        from simorgh.interface.splitscreen import SplitTui

        sampler = SystemSampler(psutil_module=_FakePsutil(), run=_ioreg(IOREG), platform="darwin", gpu_every_s=0)
        sampler.sample()
        feeds = AgentFeeds()
        feeds.started("t1", "research · notify")
        feeds.step("t1", tool="read_file", summary="notify.py", ok=True)
        got: list[str] = []

        async def on_line(line):
            got.append(line)
            print(f"sim: you said {line}")

        screen = io.StringIO()
        real_stdout = sys.stdout
        with create_pipe_input() as pipe:
            tui = SplitTui(on_line=on_line, boxes=lambda: [ProcessorBox(sampler), MemoryBox(sampler)] + feeds.boxes())
            tui.input = pipe
            tui.output = Vt100_Output(screen, lambda: Size(rows=40, columns=120), term="xterm-256color")
            run = asyncio.ensure_future(tui.run())
            try:
                await asyncio.sleep(0.3)
                pipe.send_text("hi there\r")
                await asyncio.sleep(0.4)
                pipe.send_text("\x1b[Z")        # Shift-Tab
                await asyncio.sleep(0.2)
                focus = tui.panes.focus
                pipe.send_text("\x06")          # Ctrl-F
                await asyncio.sleep(0.2)
                full = tui.panes.maximised
                pipe.send_text("\x06")
                await asyncio.sleep(0.1)
                pipe.send_text("exit\r")
                await asyncio.wait_for(run, 5)
            finally:
                sys.stdout = real_stdout
        drawn = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", screen.getvalue())
        self.assertEqual(got, ["hi there"])
        self.assertEqual((focus, full), (1, 1))
        for part in ("CPU · GPU", "Memory · numbers", "research · notify", "conversation", "sim: you said hi there"):
            self.assertIn(part, drawn)
        self.assertIs(sys.stdout, real_stdout, "stdout is given back when the screen closes")


if __name__ == "__main__":
    unittest.main()
