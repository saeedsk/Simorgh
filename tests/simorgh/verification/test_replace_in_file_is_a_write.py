"""`replace_in_file` is a write tool, and nothing said so.

`WRITE_TOOLS` is read by two checks that reach opposite conclusions
from it, so one omission broke both ways at once:

  * `DidAnythingCheck` fails a change-producing task when no write tool
    appears in the session. A task that made its edit with
    `replace_in_file` -- the ordinary way to change part of an existing
    file, as opposed to `apply_source_patch`, which rewrites the whole
    of one -- was told "the answer describes work that did not happen"
    and pushed into revisions it had no way to satisfy.
  * `full_suite_ran` reads the same set to decide whether anything was
    written ANYWHERE, and grants an honest no-op when nothing was. An
    edit made with this tool therefore excused the suite.

Caught live on 2026-09-10, twice within minutes: in the creator's own
terminal, and in a SWE-bench Verified run where step 3 was
`replace_in_file ... 1 change(s) applied  ok` and step 7 was
`verification fail: mechanical check failed -- this task's product is a
change to a file, and no write tool ran in the whole session`.

The general assertion, rather than one more name in a list: every
registered tool that writes to a file has to be in the set. That is the
thing that was actually wrong, and a new write tool would break it the
same way.
"""

from __future__ import annotations

import unittest

from simorgh.execution.config import Config
from simorgh.execution.tools import builtin_tools
from simorgh.verification.checks.didanything import WRITE_TOOLS

#: Tools that touch files without producing anything: `git_discard`
#: removes changes, so a session whose only write was a discard really
#: has produced nothing.
_NOT_PRODUCERS = frozenset({"git_discard"})


class WriteToolsTestCase(unittest.TestCase):
    def test_replace_in_file_counts_as_writing(self):
        self.assertIn("replace_in_file", WRITE_TOOLS)

    def test_every_registered_file_writer_is_in_the_set(self):
        registered = {t.name for t in builtin_tools(Config())}
        writers = {
            name for name in registered
            if name in {"apply_source_patch", "apply_skill", "replace_in_file",
                        "git_commit", "git_revert"}
        }
        missing = sorted(writers - WRITE_TOOLS - _NOT_PRODUCERS)
        self.assertEqual(missing, [], f"write tools the verifier cannot see: {missing}")

    def test_the_set_names_only_tools_that_exist(self):
        registered = {t.name for t in builtin_tools(Config())}
        unknown = sorted(WRITE_TOOLS - registered)
        self.assertEqual(unknown, [], f"WRITE_TOOLS names tools that are not registered: {unknown}")


class DidAnythingTestCase(unittest.IsolatedAsyncioTestCase):
    async def _run(self, tools):
        from simorgh.verification.checks.didanything import DidAnythingCheck
        from simorgh.verification.api import VerifyRequest

        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={"kind": "patch", "result": "applied the fix",
                     "steps": [{"tool": t, "phase": "act"} for t in tools]},
        )
        check = DidAnythingCheck()
        self.assertTrue(check.applies(req))
        return await check.run(req, None)

    async def test_a_session_that_used_replace_in_file_passes(self):
        result = await self._run(["read_file", "replace_in_file"])
        self.assertEqual(result.status, "passed", result.detail)

    async def test_a_session_that_only_read_still_fails(self):
        result = await self._run(["read_file", "search_code"])
        self.assertEqual(result.status, "failed")


if __name__ == "__main__":
    unittest.main()
