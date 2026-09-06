"""`load_charter` (09-guardian.md section 1): reads read-only, never
raises -- Guardian must still start even if the file is missing, since
the real boundaries live in Config, not parsed prose."""

import tempfile
import unittest
from pathlib import Path

from simorgh.guardian.charter import load_charter


class TestLoadCharter(unittest.TestCase):
    def test_reads_an_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SOUL.md"
            path.write_text("the charter text")
            self.assertEqual(load_charter(path), "the charter text")

    def test_a_missing_file_returns_a_placeholder_instead_of_raising(self):
        missing = Path("/nonexistent/does/not/exist/SOUL.md")
        text = load_charter(missing)
        self.assertIn("charter unavailable", text)
        self.assertIn("protected_subjects", text)

    def test_default_path_points_at_docs_soul_md(self):
        from simorgh.guardian.charter import DEFAULT_SOUL_PATH
        self.assertEqual(DEFAULT_SOUL_PATH, Path("docs/SOUL.md"))


if __name__ == "__main__":
    unittest.main()
