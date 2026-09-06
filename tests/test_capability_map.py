import tempfile
import unittest
from pathlib import Path

from src.orchestrator.capability_map import (
    list_capability_areas,
    list_capability_modules,
    pick_diverse_target,
)


class TestListCapabilityAreas(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_lists_top_level_src_directories_containing_python_files(self):
        (self.repo_root / "src" / "memory").mkdir(parents=True)
        (self.repo_root / "src" / "memory" / "long_term.py").write_text("X = 1\n")
        (self.repo_root / "src" / "cognition").mkdir(parents=True)
        (self.repo_root / "src" / "cognition" / "provider.py").write_text("X = 1\n")

        areas = list_capability_areas(self.repo_root)

        self.assertEqual(areas, ["cognition", "memory"])

    def test_excludes_a_directory_with_no_python_files(self):
        (self.repo_root / "src" / "empty_dir").mkdir(parents=True)

        self.assertEqual(list_capability_areas(self.repo_root), [])

    def test_excludes_skills(self):
        (self.repo_root / "src" / "agents" / "skills").mkdir(parents=True)
        (self.repo_root / "src" / "agents" / "skills" / "rocketry.py").write_text("X = 1\n")
        (self.repo_root / "src" / "agents" / "base.py").write_text("X = 1\n")

        # "agents" itself still counts (it has a real module, base.py) --
        # only the "skills" subdirectory name is excluded, checked via
        # list_capability_modules below.
        self.assertEqual(list_capability_areas(self.repo_root), ["agents"])

    def test_no_src_directory_returns_empty(self):
        self.assertEqual(list_capability_areas(self.repo_root), [])


class TestListCapabilityModules(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_lists_modules_as_repo_relative_paths(self):
        (self.repo_root / "src" / "memory").mkdir(parents=True)
        (self.repo_root / "src" / "memory" / "long_term.py").write_text("X = 1\n")
        (self.repo_root / "src" / "memory" / "short_term.py").write_text("X = 1\n")

        modules = list_capability_modules(self.repo_root, "memory")

        self.assertEqual(
            modules, ["src/memory/long_term.py", "src/memory/short_term.py"]
        )

    def test_excludes_skills_even_under_agents(self):
        (self.repo_root / "src" / "agents" / "skills").mkdir(parents=True)
        (self.repo_root / "src" / "agents" / "skills" / "rocketry.py").write_text("X = 1\n")
        (self.repo_root / "src" / "agents" / "base.py").write_text("X = 1\n")

        modules = list_capability_modules(self.repo_root, "agents")

        self.assertEqual(modules, ["src/agents/base.py"])

    def test_unknown_area_returns_empty(self):
        (self.repo_root / "src").mkdir()

        self.assertEqual(list_capability_modules(self.repo_root, "nonexistent"), [])


class TestPickDiverseTarget(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_returns_none_for_an_empty_codebase(self):
        self.assertIsNone(pick_diverse_target(self.repo_root, []))

    def test_returns_the_only_available_module(self):
        (self.repo_root / "src" / "memory").mkdir(parents=True)
        (self.repo_root / "src" / "memory" / "long_term.py").write_text("X = 1\n")

        self.assertEqual(
            pick_diverse_target(self.repo_root, []), "src/memory/long_term.py"
        )

    def test_avoids_a_module_in_avoid_subjects_when_an_alternative_exists(self):
        (self.repo_root / "src" / "memory").mkdir(parents=True)
        (self.repo_root / "src" / "memory" / "long_term.py").write_text("X = 1\n")
        (self.repo_root / "src" / "memory" / "short_term.py").write_text("X = 1\n")

        for _ in range(20):  # random choice -- run enough times to catch a leak
            target = pick_diverse_target(self.repo_root, ["src/memory/long_term.py"])
            self.assertEqual(target, "src/memory/short_term.py")

    def test_falls_back_to_an_avoided_module_when_nothing_else_exists(self):
        (self.repo_root / "src" / "memory").mkdir(parents=True)
        (self.repo_root / "src" / "memory" / "long_term.py").write_text("X = 1\n")

        # Only module in the whole codebase is already "avoided" -- must
        # still return it rather than None, since it's genuinely the
        # only real work available.
        self.assertEqual(
            pick_diverse_target(self.repo_root, ["src/memory/long_term.py"]),
            "src/memory/long_term.py",
        )

    def test_prefers_an_area_not_in_avoid_subjects_when_one_exists(self):
        (self.repo_root / "src" / "memory").mkdir(parents=True)
        (self.repo_root / "src" / "memory" / "long_term.py").write_text("X = 1\n")
        (self.repo_root / "src" / "cognition").mkdir(parents=True)
        (self.repo_root / "src" / "cognition" / "provider.py").write_text("X = 1\n")

        for _ in range(20):
            target = pick_diverse_target(
                self.repo_root, ["src/memory/long_term.py", "src/memory/other.py"]
            )
            self.assertTrue(target.startswith("src/cognition/"))


if __name__ == "__main__":
    unittest.main()
