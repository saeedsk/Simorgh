"""A sandbox with keys works in its own clone, never this checkout.

2026-10-27: a paid ablation run's sandboxed Sim committed two changes to
the live checkout's main and left two more in its working tree, because
Execution's repo root defaulted to this checkout."""

import asyncio
import os
import subprocess
import unittest
from pathlib import Path

from simorgh.evals.house.sandbox import Sandbox
from simorgh.execution.config import find_repo_root


def _head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


class APaidSandbox(unittest.TestCase):
    def test_its_repo_is_a_clone_and_its_commits_stay_there(self):
        live = find_repo_root()
        live_head = _head(live)
        before = os.environ.get("SIMORGH_EXECUTION_REPO_ROOT")

        async def go():
            async with Sandbox(secrets={"SOME_PROVIDER_KEY": "x"}) as box:
                root = Path(box.service("execution")._config.repo_root)  # noqa: SLF001
                self.assertNotEqual(root.resolve(), live.resolve())
                self.assertTrue(str(root).startswith(str(box.data_dir)))
                self.assertEqual(os.environ.get("SIMORGH_EXECUTION_REPO_ROOT"), str(root))
                self.assertTrue((root / "CLAUDE.md").exists(), "the clone has the checkout's files")
                subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                                "commit", "-q", "--allow-empty", "-m", "sandbox"], check=True)
                subprocess.run(["git", "-C", str(root), "branch", "-f", "main", "HEAD"], check=False)

        asyncio.run(go())
        self.assertEqual(_head(live), live_head, "the live checkout's HEAD did not move")
        self.assertEqual(os.environ.get("SIMORGH_EXECUTION_REPO_ROOT"), before, "the environment is restored")

    def test_a_free_sandbox_is_unchanged(self):
        async def go():
            async with Sandbox() as box:
                return Path(box.service("execution")._config.repo_root)  # noqa: SLF001

        self.assertEqual(asyncio.run(go()).resolve(), find_repo_root().resolve())


if __name__ == "__main__":
    unittest.main()
