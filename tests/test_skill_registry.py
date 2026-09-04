import tempfile
import unittest
from pathlib import Path

from src.agents.skills.registry import build_invocation_code, list_applied_skills, load_skill_source


class TestListAppliedSkills(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.skills_dir = self.repo_root / "src" / "agents" / "skills"
        self.skills_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_empty_directory_returns_no_skills(self):
        self.assertEqual(list_applied_skills(self.repo_root), [])

    def test_missing_directory_returns_no_skills(self):
        empty_root = Path(tempfile.mkdtemp())
        self.assertEqual(list_applied_skills(empty_root), [])

    def test_lists_applied_skills_sorted(self):
        (self.skills_dir / "zebra.py").write_text("def run():\n    return 'z'\n")
        (self.skills_dir / "apple.py").write_text("def run():\n    return 'a'\n")

        self.assertEqual(list_applied_skills(self.repo_root), ["apple", "zebra"])

    def test_excludes_infrastructure_files(self):
        (self.skills_dir / "__init__.py").write_text("")
        (self.skills_dir / "base.py").write_text("")
        (self.skills_dir / "research.py").write_text("")
        (self.skills_dir / "registry.py").write_text("")
        (self.skills_dir / "rocketry.py").write_text("def run():\n    return 'r'\n")

        self.assertEqual(list_applied_skills(self.repo_root), ["rocketry"])


class TestLoadSkillSource(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.skills_dir = self.repo_root / "src" / "agents" / "skills"
        self.skills_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_loads_existing_skill_source(self):
        (self.skills_dir / "rocketry.py").write_text("def run():\n    return 'r'\n")

        self.assertEqual(load_skill_source(self.repo_root, "rocketry"), "def run():\n    return 'r'\n")

    def test_missing_skill_returns_none(self):
        self.assertIsNone(load_skill_source(self.repo_root, "nonexistent"))

    def test_reads_fresh_from_disk_every_call_not_cached(self):
        target = self.skills_dir / "rocketry.py"
        target.write_text("def run():\n    return 'v1'\n")
        self.assertIn("v1", load_skill_source(self.repo_root, "rocketry"))

        target.write_text("def run():\n    return 'v2'\n")
        self.assertIn("v2", load_skill_source(self.repo_root, "rocketry"))

    def test_refuses_path_traversal_via_name(self):
        secret = self.repo_root / "secret.py"
        secret.write_text("SECRET = 1\n")

        self.assertIsNone(load_skill_source(self.repo_root, "../../secret"))


class TestBuildInvocationCode(unittest.TestCase):
    def test_calls_run_and_prints_result(self):
        source = "def run():\n    return 'hello'\n"
        code = build_invocation_code(source)

        namespace: dict = {}
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(code, namespace)  # noqa: S102 -- test-only, trusted local code

        self.assertEqual(buf.getvalue().strip(), "hello")

    def test_skills_own_main_guard_never_fires_directly(self):
        # The wrapper controls __name__ inside the exec'd namespace, so a
        # skill's own `if __name__ == "__main__":` block (as the
        # deterministic-fallback template writes) never fires there --
        # only the wrapper's own explicit call to run() executes.
        source = (
            "CALLS = []\n"
            "def run():\n"
            "    CALLS.append(1)\n"
            "    return str(len(CALLS))\n"
            "if __name__ == '__main__':\n"
            "    CALLS.append('main')\n"
            "    print(run())\n"
        )
        code = build_invocation_code(source)

        namespace: dict = {}
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(code, namespace)  # noqa: S102 -- test-only, trusted local code

        # If the skill's own guard had also fired, run() would have been
        # called twice and printed twice.
        self.assertEqual(buf.getvalue().strip(), "1")

    def test_missing_run_entrypoint_reports_it_instead_of_crashing(self):
        source = "VALUE = 42\n"
        code = build_invocation_code(source)

        namespace: dict = {}
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(code, namespace)  # noqa: S102 -- test-only, trusted local code

        self.assertIn("no run() entrypoint", buf.getvalue())

    def test_safely_embeds_source_containing_quotes_and_backslashes(self):
        source = 'def run():\n    return "a \\"quoted\\" \'string\'"\n'
        code = build_invocation_code(source)

        namespace: dict = {}
        exec(code, namespace)  # noqa: S102 -- test-only, trusted local code


if __name__ == "__main__":
    unittest.main()
