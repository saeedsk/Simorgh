"""A bundled skill's files are readable, and only readable (step 3)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution import pathsafety


class SkillsAreReadable(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        skill = self.root / "skills" / "pdf-reading"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: pdf-reading\ndescription: x\n---\nbody\n", encoding="utf-8")
        (skill / "extract.py").write_text("print('hi')\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_skill_file_resolves(self):
        roots = Config().readable_roots
        self.assertIn("skills", roots)
        for name in ("skills/pdf-reading/SKILL.md", "skills/pdf-reading/extract.py"):
            target, refusal = pathsafety.resolve_safe_path(self.root, name, readable_roots=roots)
            self.assertIsNone(refusal, name)
            self.assertTrue(target.exists(), name)

    def test_skills_are_not_writable_by_a_patch(self):
        self.assertNotIn("skills", Config().write_scopes_source)


if __name__ == "__main__":
    unittest.main()
