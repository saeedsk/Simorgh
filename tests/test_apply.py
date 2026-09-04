import tempfile
import unittest
from pathlib import Path

from src.memory.long_term import InMemoryStore
from src.orchestrator.apply import APPLIED_KIND, ApplyRefused, apply_proposal
from src.orchestrator.audit import ModificationProposal


class TestApplyProposal(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_writes_code_to_the_proposed_path(self):
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/agents/skills/greeting.py",
            code="print('hi')",
            rationale="a greeting skill",
        )

        target = apply_proposal(proposal, store, repo_root=self.root)

        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "print('hi')")

    def test_logs_an_applied_record(self):
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/agents/skills/greeting.py",
            code="print('hi')",
            rationale="a greeting skill",
        )

        apply_proposal(proposal, store, repo_root=self.root)

        records = store.query(kind=APPLIED_KIND)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].content, "src/agents/skills/greeting.py")
        self.assertFalse(records[0].metadata["overwrote_existing"])

    def test_tracks_overwrite_of_existing_file(self):
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/agents/skills/greeting.py",
            code="print('v1')",
            rationale="v1",
        )
        apply_proposal(proposal, store, repo_root=self.root)

        proposal_v2 = ModificationProposal(
            subject="src/agents/skills/greeting.py",
            code="print('v2')",
            rationale="v2",
        )
        apply_proposal(proposal_v2, store, repo_root=self.root)

        records = store.query(kind=APPLIED_KIND)
        self.assertTrue(records[0].metadata["overwrote_existing"])
        target = self.root / "src/agents/skills/greeting.py"
        self.assertEqual(target.read_text(), "print('v2')")

    def test_refuses_subject_outside_skills_directory(self):
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/orchestrator/router.py",
            code="print('hijacked')",
            rationale="not a skill",
        )

        with self.assertRaises(ApplyRefused):
            apply_proposal(proposal, store, repo_root=self.root)

        self.assertFalse((self.root / "src/orchestrator/router.py").exists())

    def test_refuses_path_traversal(self):
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/agents/skills/../../../etc/passwd",
            code="pwned",
            rationale="escape attempt",
        )

        with self.assertRaises(ApplyRefused):
            apply_proposal(proposal, store, repo_root=self.root)

    def test_real_protected_files_are_unreachable_regardless_of_filename(self):
        # A file that merely shares a name with a protected one (e.g.
        # src/agents/skills/soul.py) is harmless -- it's a different path
        # from the real src/orchestrator/soul.py, and the scope check
        # alone guarantees nothing outside src/agents/skills/ is ever
        # touched. AuditGate's own substring check on `subject` also
        # blocks this particular case before it would ever reach here in
        # the real propose -> audit -> apply flow; this test just confirms
        # apply_proposal's scope boundary holds on its own regardless.
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/agents/skills/soul.py",
            code="print('just a skill that happens to share a name')",
            rationale="not actually a threat -- wrong path entirely",
        )

        target = apply_proposal(proposal, store, repo_root=self.root)

        self.assertTrue(target.exists())
        self.assertNotEqual(target, (self.root / "src/orchestrator/soul.py").resolve())

    def test_creates_parent_directories(self):
        store = InMemoryStore()
        proposal = ModificationProposal(
            subject="src/agents/skills/nested/deep/skill.py",
            code="print('deep')",
            rationale="nested skill",
        )

        target = apply_proposal(proposal, store, repo_root=self.root)

        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
