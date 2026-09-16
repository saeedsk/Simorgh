"""The skills that ship with Sim (design section 5.6, build step 6)."""

from __future__ import annotations

import unittest
from pathlib import Path

from simorgh.contracts.skills import discover_skills, review_skill

BUNDLED = Path("skills")


class WhatShipsWithSim(unittest.TestCase):
    def test_the_bundled_set_is_small_and_on_mission(self):
        cards, invalid = discover_skills([("bundled", BUNDLED)])
        names = sorted(c.name for c in cards)
        self.assertEqual(names, ["mcp-builder", "skill-creator"],
                         "a curated few: the catalog is paid for on every model call")
        self.assertEqual(invalid, [])

    def test_every_bundled_skill_passes_its_own_review(self):
        for name in ("skill-creator", "mcp-builder"):
            review = review_skill(BUNDLED / name)
            self.assertTrue(review.clean, f"{name}: {[f.label for f in review.blocking]}")

    def test_every_bundled_skill_is_open_licensed_and_keeps_its_licence(self):
        for name in ("skill-creator", "mcp-builder"):
            review = review_skill(BUNDLED / name)
            self.assertTrue(review.open_licence, f"{name} licence: {review.licence[:60]}")
            self.assertTrue((BUNDLED / name / "LICENSE.txt").is_file())

    def test_the_notice_says_where_they_came_from(self):
        notice = (BUNDLED / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("github.com/anthropics/skills", notice)
        self.assertIn("Apache", notice)
        self.assertIn("source-available", notice, "and why the document skills are NOT here")


if __name__ == "__main__":
    unittest.main()
