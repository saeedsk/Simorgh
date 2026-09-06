import tempfile
import unittest
from pathlib import Path

from simorgh.worldmodel.facets.capability_map import list_capability_areas, list_capability_modules


class TestCapabilityMap(unittest.TestCase):
    def test_areas_and_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "memory").mkdir(parents=True)
            (root / "src" / "memory" / "long_term.py").write_text("X = 1\n")
            (root / "src" / "agents" / "skills").mkdir(parents=True)
            (root / "src" / "agents" / "skills" / "rocketry.py").write_text("X = 1\n")
            (root / "src" / "agents" / "base.py").write_text("X = 1\n")

            self.assertEqual(list_capability_areas(root), ["agents", "memory"])
            self.assertEqual(list_capability_modules(root, "agents"), ["src/agents/base.py"])
            self.assertEqual(list_capability_modules(root, "memory"), ["src/memory/long_term.py"])

    def test_no_src_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_capability_areas(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
