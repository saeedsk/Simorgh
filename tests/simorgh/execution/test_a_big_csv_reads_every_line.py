"""A big .tsv/.csv is read as text, every line reachable by range
(2026-10-28: a 3001-line index read as "lines 1-5 of 201")."""

import tempfile
import unittest
from pathlib import Path

from simorgh.execution.pathsafety import safe_read_lines


class ABigCsvReadsEveryLine(unittest.TestCase):
    def test_every_line_is_counted_and_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace").mkdir()
            lines = ["size\tpath"] + [f"{i}\tf{i}.jpg" for i in range(3000)]
            for name in ("index.tsv", "index.csv"):
                (root / "workspace" / name).write_text("\n".join(lines) + "\n")
                head = safe_read_lines(root, f"workspace/{name}", start=1, end=5, readable_roots=("workspace",))
                self.assertIn("of 3001", head)
                tail = safe_read_lines(root, f"workspace/{name}", start=2990, end=3001, readable_roots=("workspace",))
                self.assertIn("2999\tf2999.jpg", tail)


if __name__ == "__main__":
    unittest.main()
