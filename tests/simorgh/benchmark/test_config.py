"""`[benchmark]` declares only keys something reads.

`concurrency` was declared and never read (cases always ran one at a
time); it was removed 2026-09-19 rather than wired, because the system
under test has one worker and a shared budget.
"""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from simorgh.benchmark.config import Config


class TestNoUnreadKeys(unittest.TestCase):
    def test_concurrency_is_not_a_key(self) -> None:
        self.assertNotIn("concurrency", {f.name for f in dataclasses.fields(Config)})

    def test_a_leftover_concurrency_key_is_ignored(self) -> None:
        self.assertEqual(Config.from_mapping({"concurrency": 4, "default_cases": 3}), Config(default_cases=3))



class TheRepoRootIsTheOneTheFileToolsRead(unittest.TestCase):
    """2026-09-29: a benchmark copy imports this package from the main repo,
    so the package's own location put every GAIA attachment in the live
    checkout while Sim read the copy."""

    def test_the_configured_root_wins(self):
        from simorgh.benchmark.service import Service
        service = Service(config=Config.from_mapping({"repo_root": "/tmp/bench-copy"}))
        self.assertEqual(service._repo_root(), Path("/tmp/bench-copy"))  # noqa: SLF001

    def test_unset_is_this_packages_checkout(self):
        from simorgh.benchmark.service import Service
        import simorgh
        self.assertEqual(Service(config=Config())._repo_root(), Path(simorgh.__file__).resolve().parents[1])  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
