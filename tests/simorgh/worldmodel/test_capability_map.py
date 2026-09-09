import tempfile
import unittest
from pathlib import Path

from simorgh.worldmodel.facets.capability_map import list_capability_areas, list_capability_modules


class TestCapabilityMap(unittest.TestCase):
    def test_areas_and_modules(self):
        # `simorgh/`, not `src/`: v1's retired tree was scanned here by
        # mistake until 2026-09-08, so Sim's own answer to "what
        # subsystems make you up" named v1's six directories, and
        # Curiosity's self-directed exploration read the same wrong
        # inventory. This fixture builds the live tree's shape.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "simorgh" / "memory").mkdir(parents=True)
            (root / "simorgh" / "memory" / "long_term.py").write_text("X = 1\n")
            (root / "simorgh" / "agents" / "skills").mkdir(parents=True)
            (root / "simorgh" / "agents" / "skills" / "rocketry.py").write_text("X = 1\n")
            (root / "simorgh" / "agents" / "base.py").write_text("X = 1\n")

            self.assertEqual(list_capability_areas(root), ["agents", "memory"])
            self.assertEqual(list_capability_modules(root, "agents"), ["simorgh/agents/base.py"])
            self.assertEqual(list_capability_modules(root, "memory"), ["simorgh/memory/long_term.py"])

    def test_no_simorgh_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_capability_areas(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
