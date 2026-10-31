"""A protected path matches at the start of a path component, not inside a
longer name.

Live 2026-10-30: a `run_shell` that began `cd ~/.simorgh/execution/
worktrees/9a7fa1414803 2>/dev/null; ls ...` was denied as an edit of
`simorgh/execution/` -- Sim's own data directory `.simorgh/execution/`
contains that text -- so no shell command could run in any task's
worktree. Every real path into a protected package must still be refused.
"""

from __future__ import annotations

import unittest

from simorgh.guardian.api import DecisionContext, Proposal
from simorgh.guardian.config import Config
from simorgh.guardian.posture import Posture
from simorgh.guardian.rules import ProtectedRule, _at_boundary


def _ctx() -> DecisionContext:
    return DecisionContext(now=0.0, system_state="running", posture=Posture(level="guarded"), config=Config())


def _shell(command: str) -> Proposal:
    return Proposal(action_id="a1", tool="run_shell", args={"command": command}, scope={"paths": []},
                    reversibility="reversible", rationale="", proposed_by="orchestration")


def _write(path: str) -> Proposal:
    return Proposal(action_id="a1", tool="apply_source_patch", args={"path": path, "content": "x"},
                    scope={"paths": [path]}, reversibility="irreversible", rationale="", proposed_by="orchestration")


class AtABoundary(unittest.TestCase):
    def test_inside_a_longer_name_is_not_a_match(self):
        self.assertFalse(_at_boundary("simorgh/execution/", "/users/saeed/.simorgh/execution/worktrees/9a7f"))
        self.assertFalse(_at_boundary("agents/", "docs/subagents/notes.md"))
        self.assertFalse(_at_boundary("simloader.py", "tools/old_simloader.py"))

    def test_a_real_path_is(self):
        for path in ("simorgh/execution/tools.py", "/users/saeed/ws/simorgh/simorgh/execution/tools.py",
                     "./simorgh/execution/x.py", "'simorgh/execution/x.py'", ">simorgh/execution/x.py",
                     "/users/saeed/.simorgh/execution/worktrees/9a7f/simorgh/execution/tools.py"):
            self.assertTrue(_at_boundary("simorgh/execution/", path), path)


class TheRule(unittest.IsolatedAsyncioTestCase):
    async def test_a_command_in_its_own_worktree_is_not_an_edit_of_execution(self):
        command = ("cd /Users/saeed/.simorgh/execution/worktrees/9a7fa1414803 2>/dev/null || cd /Users/saeed/ws/Simorgh; "
                   "ls -la workspace/music 2>/dev/null; git status --short | head -20")
        decision = await ProtectedRule().evaluate(_shell(command), _ctx())
        self.assertEqual(decision.kind, "abstain", decision.reasons)

    async def test_writing_execution_is_still_refused_however_it_is_named(self):
        for path in ("simorgh/execution/tools.py", "/Users/saeed/ws/Simorgh/simorgh/execution/tools.py",
                     "SIMORGH/EXECUTION/tools.py", "simorgh//execution/tools.py",
                     "/Users/saeed/.simorgh/execution/worktrees/9a7f/simorgh/execution/tools.py"):
            self.assertEqual((await ProtectedRule().evaluate(_write(path), _ctx())).kind, "deny", path)

    async def test_a_shell_write_into_a_protected_package_is_still_refused(self):
        decision = await ProtectedRule().evaluate(_shell("echo x > simorgh/guardian/rules.py"), _ctx())
        self.assertEqual(decision.kind, "deny")


if __name__ == "__main__":
    unittest.main()
