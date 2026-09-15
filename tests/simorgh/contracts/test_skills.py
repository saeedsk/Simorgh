"""Agent Skills parsing (docs/plans/agent-skills-design.md section 3.1)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.skills import InvalidSkill, SkillCard, catalog_text, discover_skills, load_body, parse_skill


def _skill(root: Path, folder: str, text: str) -> Path:
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d / "SKILL.md"


GOOD = """---
name: pdf-reading
description: "Read household PDFs: bills, statements, school letters"
allowed_profiles: [research, chat]
---
# Reading a PDF

1. Extract the text with the pdf tool.
"""


class Parse(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_valid_skill(self):
        card = parse_skill(_skill(self.root, "pdf", GOOD), source="bundled")
        self.assertIsInstance(card, SkillCard)
        self.assertEqual(card.name, "pdf-reading")
        self.assertEqual(card.description, "Read household PDFs: bills, statements, school letters")
        self.assertEqual(card.allowed_profiles, ("research", "chat"))
        self.assertEqual(len(card.sha256), 64)
        self.assertIn("Extract the text", load_body(card))
        self.assertNotIn("allowed_profiles", load_body(card))

    def test_block_lists_and_bad_skills(self):
        block = parse_skill(_skill(self.root, "b", "---\nname: b-skill\ndescription: x\nallowed_profiles:\n  - patch\n  - research\n---\nbody"), source="s")
        self.assertEqual(block.allowed_profiles, ("patch", "research"))
        cases = {
            "no-front": "# just markdown",
            "bad-name": "---\nname: Bad Name\ndescription: x\n---\n",
            "no-desc": "---\nname: fine\n---\n",
        }
        for folder, text in cases.items():
            result = parse_skill(_skill(self.root, folder, text), source="s")
            self.assertIsInstance(result, InvalidSkill, folder)
            self.assertTrue(result.reason)

    def test_discovery_ranks_roots_and_reports_invalid(self):
        first, second = self.root / "bundled", self.root / "installed"
        _skill(first, "pdf", GOOD)
        _skill(second, "pdf", GOOD.replace("household PDFs", "any PDFs"))
        _skill(second, "other", "---\nname: other\ndescription: another skill\n---\nbody")
        _skill(second, "broken", "no frontmatter")
        cards, invalid = discover_skills([("bundled", first), ("installed", second), ("missing", self.root / "nope")])
        self.assertEqual([c.name for c in cards], ["other", "pdf-reading"])
        self.assertEqual(next(c for c in cards if c.name == "pdf-reading").source, "bundled", "the first root wins")
        self.assertEqual(len(invalid), 2, invalid)

    def test_catalog_caps_and_filters(self):
        cards = [SkillCard(name=f"s{i:02d}", description="x" * 50, source="t", path=self.root) for i in range(40)]
        text = catalog_text(cards, max_chars=300)
        self.assertLessEqual(len(text), 360)
        self.assertIn("more not listed", text)
        only_patch = SkillCard(name="p", description="patch only", source="t", path=self.root, allowed_profiles=("patch",))
        self.assertEqual(catalog_text([only_patch], profile="chat"), "")
        self.assertIn("patch only", catalog_text([only_patch], profile="patch"))


if __name__ == "__main__":
    unittest.main()
