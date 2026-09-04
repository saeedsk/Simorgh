import subprocess
import tempfile
import unittest
from pathlib import Path

from src.orchestrator.git_ops import (
    CommitResult,
    commit_applied_change,
    current_commit_hash,
    revert_commits_since,
    revert_last_commit,
)


def _run_git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=True)


class TestCommitAppliedChangeAgainstARealRepo(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        _run_git(self.repo_root, "init", "-q")
        _run_git(self.repo_root, "config", "user.email", "test@example.com")
        _run_git(self.repo_root, "config", "user.name", "Test")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_commits_a_new_file(self):
        (self.repo_root / "skill.py").write_text("def run():\n    return 1\n")

        result = commit_applied_change(self.repo_root, "skill.py", "[sim] Add skill: skill.py")

        self.assertTrue(result.committed)
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=self.repo_root, capture_output=True, text=True
        )
        self.assertIn("Add skill", log.stdout)

    def test_commit_is_attributed_to_simorgh_not_the_repo_default_identity(self):
        (self.repo_root / "skill.py").write_text("def run():\n    return 1\n")

        commit_applied_change(self.repo_root, "skill.py", "[sim] Add skill: skill.py")

        author = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        self.assertIn("Simorgh", author.stdout)
        self.assertNotIn("Test <test@example.com>", author.stdout)

    def test_never_touches_the_repositorys_persistent_git_config(self):
        (self.repo_root / "skill.py").write_text("def run():\n    return 1\n")

        commit_applied_change(self.repo_root, "skill.py", "[sim] Add skill: skill.py")

        name = subprocess.run(
            ["git", "config", "user.name"], cwd=self.repo_root, capture_output=True, text=True
        )
        self.assertEqual(name.stdout.strip(), "Test")

    def test_does_not_stage_unrelated_uncommitted_files(self):
        (self.repo_root / "skill.py").write_text("def run():\n    return 1\n")
        (self.repo_root / "unrelated.py").write_text("UNRELATED = 1\n")

        commit_applied_change(self.repo_root, "skill.py", "[sim] Add skill: skill.py")

        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=self.repo_root, capture_output=True, text=True
        )
        self.assertIn("unrelated.py", status.stdout)
        self.assertNotIn("skill.py", status.stdout)

    def test_nothing_to_commit_is_reported_not_raised(self):
        (self.repo_root / "skill.py").write_text("def run():\n    return 1\n")
        commit_applied_change(self.repo_root, "skill.py", "[sim] first")

        result = commit_applied_change(self.repo_root, "skill.py", "[sim] second, no changes")

        self.assertFalse(result.committed)


class TestCommitAppliedChangeFailureModes(unittest.TestCase):
    def test_not_a_git_repository_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skill.py").write_text("def run():\n    return 1\n")

            result = commit_applied_change(root, "skill.py", "msg")

            self.assertFalse(result.committed)
            self.assertIn("git add failed", result.output)

    def test_missing_git_binary_is_reported_not_raised(self):
        def raising_runner(*args, **kwargs):
            raise OSError("no such file: git")

        with tempfile.TemporaryDirectory() as tmp:
            result = commit_applied_change(Path(tmp), "skill.py", "msg", runner=raising_runner)

        self.assertFalse(result.committed)
        self.assertIn("failed to run git", result.output)

    def test_timeout_is_reported_not_raised(self):
        def timing_out_runner(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=1.0)

        with tempfile.TemporaryDirectory() as tmp:
            result = commit_applied_change(
                Path(tmp), "skill.py", "msg", timeout=1.0, runner=timing_out_runner
            )

        self.assertFalse(result.committed)
        self.assertIn("timed out", result.output)

    def test_result_type_is_commit_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = commit_applied_change(Path(tmp), "skill.py", "msg")

        self.assertIsInstance(result, CommitResult)


class TestRevertLastCommit(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        _run_git(self.repo_root, "init", "-q")
        _run_git(self.repo_root, "config", "user.email", "test@example.com")
        _run_git(self.repo_root, "config", "user.name", "Test")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_reverts_the_last_commit_restoring_prior_content(self):
        target = self.repo_root / "skill.py"
        target.write_text("VALUE = 1\n")
        commit_applied_change(self.repo_root, "skill.py", "[sim] first version")
        target.write_text("VALUE = 2\n")
        commit_applied_change(self.repo_root, "skill.py", "[sim] second version, broken")

        result = revert_last_commit(self.repo_root)

        self.assertTrue(result.committed)
        self.assertEqual(target.read_text(), "VALUE = 1\n")

    def test_revert_is_attributed_to_simorgh(self):
        target = self.repo_root / "skill.py"
        target.write_text("VALUE = 1\n")
        commit_applied_change(self.repo_root, "skill.py", "[sim] first version")

        revert_last_commit(self.repo_root)

        author = subprocess.run(
            ["git", "log", "-1", "--format=%an"], cwd=self.repo_root, capture_output=True, text=True
        )
        self.assertIn("Simorgh", author.stdout)

    def test_failure_on_a_repo_with_nothing_to_revert_is_reported_not_raised(self):
        result = revert_last_commit(self.repo_root)

        self.assertFalse(result.committed)

    def test_missing_git_binary_is_reported_not_raised(self):
        def raising_runner(*args, **kwargs):
            raise OSError("no such file: git")

        result = revert_last_commit(self.repo_root, runner=raising_runner)

        self.assertFalse(result.committed)
        self.assertIn("failed to run git", result.output)


class TestCurrentCommitHash(unittest.TestCase):
    def test_returns_the_head_hash_in_a_real_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _run_git(root, "init", "-q")
            _run_git(root, "config", "user.email", "test@example.com")
            _run_git(root, "config", "user.name", "Test")
            (root / "f.py").write_text("X = 1\n")
            _run_git(root, "add", "-A")
            _run_git(root, "commit", "-q", "-m", "initial")

            result = current_commit_hash(root)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 40)  # a full git SHA-1

    def test_returns_none_for_a_non_git_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = current_commit_hash(Path(tmp))

        self.assertIsNone(result)

    def test_returns_none_when_git_is_missing(self):
        def raising_runner(*args, **kwargs):
            raise OSError("no such file: git")

        with tempfile.TemporaryDirectory() as tmp:
            result = current_commit_hash(Path(tmp), runner=raising_runner)

        self.assertIsNone(result)


class TestRevertCommitsSince(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        _run_git(self.repo_root, "init", "-q")
        _run_git(self.repo_root, "config", "user.email", "test@example.com")
        _run_git(self.repo_root, "config", "user.name", "Test")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_reverts_multiple_commits_back_to_the_base(self):
        target = self.repo_root / "a.py"
        target.write_text("A = 1\n")
        commit_applied_change(self.repo_root, "a.py", "[sim] a v1")
        base = current_commit_hash(self.repo_root)

        target.write_text("A = 2\n")
        commit_applied_change(self.repo_root, "a.py", "[sim] a v2")
        other = self.repo_root / "b.py"
        other.write_text("B = 1\n")
        commit_applied_change(self.repo_root, "b.py", "[sim] b v1")

        result = revert_commits_since(self.repo_root, base)

        self.assertTrue(result.committed)
        self.assertEqual(target.read_text(), "A = 1\n")
        self.assertFalse(other.exists())

    def test_reverts_are_attributed_to_simorgh(self):
        target = self.repo_root / "a.py"
        target.write_text("A = 1\n")
        commit_applied_change(self.repo_root, "a.py", "[sim] a v1")
        base = current_commit_hash(self.repo_root)
        target.write_text("A = 2\n")
        commit_applied_change(self.repo_root, "a.py", "[sim] a v2")

        revert_commits_since(self.repo_root, base)

        author = subprocess.run(
            ["git", "log", "-1", "--format=%an"], cwd=self.repo_root, capture_output=True, text=True
        )
        self.assertIn("Simorgh", author.stdout)

    def test_failure_is_reported_not_raised(self):
        result = revert_commits_since(self.repo_root, "not-a-real-commit-hash")

        self.assertFalse(result.committed)


if __name__ == "__main__":
    unittest.main()
