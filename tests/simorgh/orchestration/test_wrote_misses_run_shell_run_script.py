"""`Session.wrote` -- the set the 2026-09-09 verification checks
(`js_syntax`, `render`, `trailing_narration`, `full_suite_ran`) trust to
know which files a session touched -- is populated in
`SessionRunner._propose_and_await` (session.py) purely by pattern-
matching a `side_effects` entry's *kind* prefix against
`"file_write"`/`"file_create"`.

Two real, reachable write tools never emit either kind:

- `execution/shell.py::RunShellTool` reports
  `side_effects=(f"run_shell:{_head(command)}",)` -- kind `"run_shell"`,
  which `_propose_and_await`'s branch (`kind == "file_write"` /
  `kind == "file_create"`) does not match. A shell command that writes
  or overwrites any file in the repo (`echo ... > docs/games/x.html`,
  `sed -i`, a heredoc) leaves `session.wrote` untouched.
- `execution/script.py::RunScriptTool` runs with the repo importable
  and as its cwd, but its `ToolResult(...)` never passes `side_effects`
  at all -- a Python script that does `Path("docs/games/x.html")
  .write_text(...)` is invisible to `session.wrote` even in principle.

Consequence: a task that writes a broken `.html`/`.js` file through
either tool (rather than `apply_source_patch`/`apply_skill`) makes
`written_paths` empty for that file, so `js_syntax`, `render`, and
`trailing_narration` (which all gate on `written_paths(...,
suffixes=...)` being non-empty) silently `skipped` it -- exactly the
blind spot these checks were built 2026-09-09 to close, still open for
any task that routes its write through `run_shell` or `run_script`.

These tests drive the real `_propose_and_await` over a real bus/ledger
harness (same pattern as `test_verify_subject_truncation.py`), with a
subscriber that answers like the real tools actually do, and show
`session.wrote`/`session.uncommitted` stay empty after each.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.orchestration.api import Session
from simorgh.orchestration import profiles
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run


class TestRunShellWriteIsInvisibleToWritten(unittest.TestCase):
    @run
    async def test_a_run_shell_file_write_never_lands_in_session_wrote(self):
        async with Harness() as h:
            bus = h.client("orchestration")

            async def _answer_like_real_run_shell(message):
                # Exactly what RunShellTool.run() reports on success:
                # side_effects=(f"run_shell:{_head(command)}",) -- see
                # execution/shell.py.
                reply = message.caused(topics.ACTION_RESULT, {
                    "action_id": message.payload["action_id"], "ok": True,
                    "output_ref": "", "stdout_preview": "wrote docs/games/shell_written.html",
                    "duration_ms": 5,
                    "side_effects": ["run_shell:echo '<html></html' > docs/games/shell_written.html"],
                }, source="execution")
                await bus.publish(reply)

            sub = await bus.subscribe(topics.ACTION_PROPOSED, _answer_like_real_run_shell)

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t-shell", kind="patch", mode="execute", profile=profiles.PATCH)
            call = {"tool": "run_shell", "args": {"command": "echo '<html></html' > docs/games/shell_written.html"}}
            ok, _bounded, _full = await runner._propose_and_await(session, call, step_no=1)
            await sub.unsubscribe()

            self.assertTrue(ok)
            # The bug: a real file write through run_shell reports no
            # opinion to session.wrote/uncommitted/created at all.
            self.assertEqual(session.wrote, set())
            self.assertEqual(session.uncommitted, set())
            self.assertEqual(session.created, set())


class TestRunScriptWriteIsInvisibleToWritten(unittest.TestCase):
    @run
    async def test_a_run_script_file_write_never_lands_in_session_wrote(self):
        async with Harness() as h:
            bus = h.client("orchestration")

            async def _answer_like_real_run_script(message):
                # RunScriptTool.run() never passes side_effects at all
                # (execution/script.py) -- even though the script ran
                # with the repo importable and as its cwd and can write
                # any file in it.
                reply = message.caused(topics.ACTION_RESULT, {
                    "action_id": message.payload["action_id"], "ok": True,
                    "output_ref": "", "stdout_preview": "done",
                    "duration_ms": 5, "side_effects": [],
                }, source="execution")
                await bus.publish(reply)

            sub = await bus.subscribe(topics.ACTION_PROPOSED, _answer_like_real_run_script)

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t-script", kind="patch", mode="execute", profile=profiles.PATCH)
            call = {
                "tool": "run_script",
                "args": {"code": "from pathlib import Path\n"
                                  "Path('docs/games/script_written.html').write_text('<html></html')\n"},
            }
            ok, _bounded, _full = await runner._propose_and_await(session, call, step_no=1)
            await sub.unsubscribe()

            self.assertTrue(ok)
            self.assertEqual(session.wrote, set())
            self.assertEqual(session.uncommitted, set())
            self.assertEqual(session.created, set())
