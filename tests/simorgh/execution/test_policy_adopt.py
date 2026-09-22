"""`policy_adopt` writes an adopted lesson into rules/ and commits it
(stage 8 item 5). Guardian asks a person first; that is its own test."""

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.policyadopt import PolicyAdoptTool


class Adopting(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                    ["commit", "-q", "--allow-empty", "-m", "start"]):
            subprocess.run(["git", *cmd], cwd=self.root, check=True)
        self.tool = PolicyAdoptTool(Config(repo_root=self.root))
        self.ctx = ToolContext(action_id="a", task_id=None, scope={}, constraints={}, data_dir=self.root,
                               clock=None, logger=None, ledger=None)

    def _run(self, **args):
        base = {"task_type": "patch", "path": "rules/patch.md", "policy_id": "p1",
                "rule": "Run the whole suite before committing."}
        return asyncio.run(self.tool.run({**base, **args}, ctx=self.ctx))

    def test_it_writes_and_commits_one_file(self):
        result = self._run()
        self.assertTrue(result.ok, result.error)
        self.assertIn("- Run the whole suite before committing.", (self.root / "rules/patch.md").read_text())
        log = subprocess.run(["git", "log", "--oneline", "-1", "--", "rules/patch.md"], cwd=self.root,
                             capture_output=True, text=True).stdout
        self.assertIn("adopt policy p1", log)
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=self.root,
                                        capture_output=True, text=True).stdout, "")

    def test_the_same_rule_twice_is_one_line(self):
        self._run()
        self.assertTrue(self._run().metadata.get("unchanged"))

    def test_it_writes_only_its_own_file(self):
        self.assertFalse(self._run(path="simorgh/guardian/rules.py").ok)
        self.assertFalse(self._run(task_type="../agents").ok)
        self.assertFalse((self.root / "agents").exists())


if __name__ == "__main__":
    unittest.main()
