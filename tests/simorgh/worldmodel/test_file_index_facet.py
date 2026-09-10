"""The file index must answer the question it was asked.

One unkeyed cache slot, filled by the first call the process ever made,
answered every later one: asking for `src` returned the 308 files of
`simorgh`, labelled `"under": "simorgh"`. Not a refusal, not an empty
result -- a confidently wrong answer about Sim's own code (observer,
2026-09-10).

And nothing anywhere calls `invalidate()`, so that snapshot was the
answer for the life of the process, while `capability_map` beside it
has no cache and sees the tree as it is. Curiosity picks what to
explore from this listing.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.worldmodel.facets.file_index import FileIndexFacet


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FileIndexAnswersWhatWasAskedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for area, count in (("alpha", 3), ("beta", 1)):
            (self.root / area).mkdir()
            for index in range(count):
                (self.root / area / f"m{index}.py").write_text("x = 1\n")
        self.clock = _Clock()
        self.facet = FileIndexFacet(self.root, refresh_seconds=30.0, clock=self.clock)

    def _get(self, args: dict) -> dict:
        return asyncio.run(self.facet.get(args))

    def test_a_second_question_is_not_answered_with_the_first_answer(self):
        first = self._get({"under": "alpha"})
        second = self._get({"under": "beta"})
        self.assertEqual((first["under"], len(first["files"])), ("alpha", 3))
        self.assertEqual((second["under"], len(second["files"])), ("beta", 1))

    def test_the_label_matches_the_listing(self):
        """The wrong answer was also mislabelled, which is what made it
        impossible to notice."""
        listing = self._get({"under": "beta"})
        self.assertTrue(all(f["path"].startswith("beta/") for f in listing["files"]))

    def test_a_repeat_inside_the_window_is_served_from_cache(self):
        first = self._get({"under": "alpha"})
        (self.root / "alpha" / "new.py").write_text("y = 2\n")
        self.assertEqual(len(self._get({"under": "alpha"})["files"]), len(first["files"]))

    def test_the_listing_goes_stale_and_is_rescanned(self):
        self._get({"under": "alpha"})
        (self.root / "alpha" / "new.py").write_text("y = 2\n")
        self.clock.t += 31.0
        self.assertEqual(len(self._get({"under": "alpha"})["files"]), 4)

    def test_every_listing_says_when_it_was_scanned(self):
        """The envelope's `as_of` is when the question was asked, which
        says nothing about how old the answer is."""
        self.assertEqual(self._get({"under": "alpha"})["scanned_at"], 1000.0)

    def test_invalidate_clears_every_key(self):
        self._get({"under": "alpha"})
        self._get({"under": "beta"})
        (self.root / "beta" / "extra.py").write_text("z = 3\n")
        self.facet.invalidate()
        self.assertEqual(len(self._get({"under": "beta"})["files"]), 2)

    def test_a_directory_that_does_not_exist_is_empty_and_says_so(self):
        listing = self._get({"under": "nowhere"})
        self.assertEqual((listing["under"], listing["files"]), ("nowhere", []))


if __name__ == "__main__":
    unittest.main()
