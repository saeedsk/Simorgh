"""The observer testing toolkit, built 2026-09-08 to close three real
costs a wave of observers kept paying: slow per-agent sandbox copies,
scratchpad collisions, and prose findings nobody could deduplicate.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import observer_kit as kit  # noqa: E402
import aggregate_findings as agg  # noqa: E402


class TestFastCopyRepo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.source = Path(self._tmp.name) / "src"
        (self.source / "sub").mkdir(parents=True)
        (self.source / "top.txt").write_text("hello")
        (self.source / "sub" / "nested.txt").write_text("world")
        (self.source / ".git").mkdir()
        (self.source / ".git" / "HEAD").write_text("ref: refs/heads/main")

    def test_the_clone_has_every_real_file(self) -> None:
        dest = Path(self._tmp.name) / "dst"
        kit.fast_copy_repo(dest, source=self.source)
        self.assertEqual((dest / "top.txt").read_text(), "hello")
        self.assertEqual((dest / "sub" / "nested.txt").read_text(), "world")

    def test_it_refuses_to_overwrite_an_existing_sandbox(self) -> None:
        dest = Path(self._tmp.name) / "dst"
        dest.mkdir()
        with self.assertRaises(FileExistsError):
            kit.fast_copy_repo(dest, source=self.source)

    def test_writing_in_one_clone_never_touches_the_other(self) -> None:
        """The whole point of a sandbox: real independence, whichever
        copy mechanism produced it."""
        dest_a = Path(self._tmp.name) / "a"
        dest_b = Path(self._tmp.name) / "b"
        kit.fast_copy_repo(dest_a, source=self.source)
        kit.fast_copy_repo(dest_b, source=self.source)
        (dest_a / "top.txt").write_text("mutated")
        self.assertEqual((dest_b / "top.txt").read_text(), "hello")
        self.assertEqual(self.source.joinpath("top.txt").read_text(), "hello")


class TestAgentWorkspace(unittest.TestCase):
    def test_two_observers_never_collide(self) -> None:
        """The exact failure mode from 2026-09-08: two observers with
        the same short name overwrote each other's files in a shared
        scratchpad. A fresh call must never return a path that already
        exists, even for the identical name."""
        with tempfile.TemporaryDirectory() as tmp:
            first = kit.agent_workspace("gaia-reader", parent=Path(tmp))
            second = kit.agent_workspace("gaia-reader", parent=Path(tmp))
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())

    def test_an_unsafe_name_still_produces_a_valid_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = kit.agent_workspace("cli / judge: round 4!", parent=Path(tmp))
            self.assertTrue(workspace.is_dir())


class TestFindingsRoundTrip(unittest.TestCase):
    """Findings live under `DEFAULT_WORKSPACE_ROOT`, not `REPO_ROOT` --
    both are outside the repo on purpose (see the module docstring), so
    this patches the one `_findings_path` actually reads. Each test uses
    its own freshly generated run id rather than a literal like "r1":
    the store is a real append-only file on disk, and a repeated literal
    would silently accumulate across test runs instead of catching a
    real mixing bug.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_root = kit.DEFAULT_WORKSPACE_ROOT
        kit.DEFAULT_WORKSPACE_ROOT = Path(self._tmp.name)
        self.addCleanup(lambda: setattr(kit, "DEFAULT_WORKSPACE_ROOT", self._orig_root))

    def test_a_recorded_finding_is_loadable(self) -> None:
        run_id = kit.new_run_id("test")
        kit.record_finding("obs-1", "blocker", "the loader rolls forward", run_id=run_id,
                           category="loader", file="simloader.py", line=42)
        loaded = kit.load_findings(run_id)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].observer, "obs-1")
        self.assertEqual(loaded[0].line, 42)

    def test_an_unknown_run_id_loads_as_empty_not_an_error(self) -> None:
        self.assertEqual(kit.load_findings("never-recorded"), [])

    def test_findings_from_different_runs_do_not_mix(self) -> None:
        run_a, run_b = kit.new_run_id("a"), kit.new_run_id("b")
        kit.record_finding("obs-1", "blocker", "a", run_id=run_a)
        kit.record_finding("obs-2", "blocker", "b", run_id=run_b)
        self.assertEqual(len(kit.load_findings(run_a)), 1)
        self.assertEqual(len(kit.load_findings(run_b)), 1)


class TestClusteringDedupesRealObserverOverlap(unittest.TestCase):
    """Today's wave: four observers independently found the identical
    marker-truncation defect in different files. A coordinator reading
    that as four separate paragraphs is the exact waste this closes."""

    def test_the_same_file_and_category_cluster_together(self) -> None:
        findings = [
            kit.Finding(observer="o1", severity="blocker", summary="RUN_SHELL truncated to its first line",
                       category="marker-truncation", file="simorgh/cognition/parser.py", line=45),
            kit.Finding(observer="o2", severity="blocker", summary="run_shell only sees line 1 of a heredoc",
                       category="marker-truncation", file="simorgh/cognition/parser.py", line=45),
            kit.Finding(observer="o3", severity="degraded", summary="status panel shows two postures",
                       category="stale-cache", file="simorgh/interface/vitals.py", line=98),
        ]
        clusters = agg.cluster(findings)
        self.assertEqual(len(clusters), 2)
        marker_cluster = next(c for c in clusters if c["category"] == "marker-truncation")
        self.assertEqual(marker_cluster["count"], 2)
        self.assertEqual(set(marker_cluster["observers"]), {"o1", "o2"})

    def test_blockers_are_ranked_before_degraded_findings(self) -> None:
        findings = [
            kit.Finding(observer="o1", severity="cosmetic", summary="a", category="c1", file="x.py"),
            kit.Finding(observer="o2", severity="blocker", summary="b", category="c2", file="y.py"),
        ]
        clusters = agg.cluster(findings)
        self.assertEqual(clusters[0]["severity"], "blocker")

    def test_findings_with_no_file_still_cluster_by_wording(self) -> None:
        """Most CLI/behavioural findings name no file. They should still
        dedupe when independent observers describe the same thing in
        similar words, without merging genuinely different findings."""
        findings = [
            kit.Finding(observer="o1", severity="degraded", summary="bare auto prints the kernel state not autonomy",
                       category="auto-command"),
            kit.Finding(observer="o2", severity="degraded", summary="bare auto prints kernel state instead of autonomy",
                       category="auto-command"),
            kit.Finding(observer="o3", severity="degraded", summary="cancel always claims success even for a bad id",
                       category="cancel-command"),
        ]
        clusters = agg.cluster(findings)
        self.assertEqual(len(clusters), 2)

    def test_render_produces_readable_text_including_empty(self) -> None:
        self.assertIn("no findings", agg.render([]))
        text = agg.render(agg.cluster([
            kit.Finding(observer="o1", severity="blocker", summary="s", category="c", file="f.py", line=1),
        ]))
        self.assertIn("BLOCKER", text)
        self.assertIn("f.py:1", text)


if __name__ == "__main__":
    unittest.main()
