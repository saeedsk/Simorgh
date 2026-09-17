"""`console_tail`: Sim reading its own console (execution/tools.py).

The creator, live 2026-09-16, watching red lines scroll past: "what was
the red message? what was happening?" Sim made three tool calls --
`list_tasks` (two task titles, no errors), `read_file` on a log that
does not exist (refused), `search_code` (no matches) -- and then spent
11.8s, the slowest model turn of the session, composing this:

    "three repeats of a vision API rate-limit error (429), plus the
    garden camera timing out on its snapshots a couple of times ... the
    front camera's baseline updated fine, and the task just backed off
    and is retrying after a cooldown."

Every specific was invented. No `429` or `garden` string existed
anywhere in two hours of ledger, and `workspace/cameras/baselines.json`
had never been written. The honesty rule here is that a tool must never
succeed while saying nothing true -- but no tool was involved, which is
the point: the question had no reachable ground truth, and the gap
itself produced the fiction.

So the empty case is the most important test in this file.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import console
from simorgh.execution.config import Config
from simorgh.execution.tools import ConsoleTailTool, builtin_tools


class ConsoleTailTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patch = mock.patch.dict(os.environ, {"SIMORGH_CONFIG": str(self.home / "simorgh.toml")})
        patch.start()
        self.addCleanup(patch.stop)
        self.tool = ConsoleTailTool(Config(repo_root=self.home))

    async def test_an_empty_console_says_so_and_says_not_to_invent(self):
        """The 2026-09-16 shape: nothing to report is the exact input
        that invited a fluent invention last time."""
        result = await self.tool.run({"request": ""}, ctx=None)
        self.assertTrue(result.ok)
        self.assertIn("no console lines recorded", result.output)
        self.assertIn("do NOT describe", result.output)

    async def test_it_returns_what_was_actually_printed(self):
        console.record("[error] ring webrtc KeyError('session_id')")
        result = await self.tool.run({"request": ""}, ctx=None)
        self.assertIn("KeyError('session_id')", result.output)

    async def test_a_count_and_a_filter_are_both_read_from_the_one_string(self):
        console.record("[error] the thing that actually failed")
        for n in range(30):
            console.record(f"[info] ordinary {n}")
        result = await self.tool.run({"request": "5 error"}, ctx=None)
        self.assertIn("the thing that actually failed", result.output)
        self.assertNotIn("ordinary", result.output)

    async def test_a_bare_word_filters_without_a_count(self):
        console.record("[warn] guardian denied something")
        console.record("[info] nothing to see")
        result = await self.tool.run({"request": "guardian"}, ctx=None)
        self.assertIn("guardian denied", result.output)
        self.assertNotIn("nothing to see", result.output)

    async def test_a_filter_that_matches_nothing_still_refuses_to_invent(self):
        console.record("[info] something unrelated")
        result = await self.tool.run({"request": "429"}, ctx=None)
        self.assertIn("no console lines recorded", result.output)
        self.assertIn("'429'", result.output)

    async def test_a_number_too_big_to_be_a_count_is_searched_for_instead(self):
        """`429` is a status code, not a request for 429 lines. Reading
        it as a count is what handed the model a screenful of unrelated
        output to narrate."""
        console.record("[info] something unrelated")
        result = await self.tool.run({"request": "99999"}, ctx=None)
        self.assertIn("no console lines recorded", result.output)

    async def test_the_count_is_honoured(self):
        for n in range(250):
            console.record(f"[info] line {n}")
        result = await self.tool.run({"request": "200"}, ctx=None)
        self.assertEqual(len(result.output.splitlines()), 200)
        self.assertIn("line 249", result.output)

    def test_the_tool_is_registered(self):
        """Registering a tool takes four tables in this codebase, and
        forgetting one shipped a broken `camera_describe` on 2026-09-15."""
        names = {tool.name for tool in builtin_tools(Config(repo_root=self.home))}
        self.assertIn("console_tail", names)

    def test_the_verb_shown_on_screen_exists(self):
        from simorgh.interface import live_status
        self.assertIn(("act", "console_tail"), live_status._VERBS)  # noqa: SLF001

    def test_the_model_is_told_the_tool_exists(self):
        from simorgh.orchestration import scaffolds
        self.assertIn("console_tail", scaffolds._TOOL_NOTES)  # noqa: SLF001

    def test_the_policy_row_exists_and_is_read_only(self):
        from simorgh.orchestration import tools as orch_tools
        self.assertEqual(orch_tools._TOOL_POLICY["console_tail"], ("read_only", True))  # noqa: SLF001

    def test_the_single_string_argument_is_named(self):
        from simorgh.contracts import toolargs
        self.assertEqual(toolargs.MARKER_ARG_KEY["console_tail"], "request")


if __name__ == "__main__":
    unittest.main()
