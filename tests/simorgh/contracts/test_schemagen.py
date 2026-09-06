import json
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import schemagen


class TestSchemagen(unittest.TestCase):
    def test_checked_in_schemas_are_in_sync(self):
        problems = schemagen.check()
        self.assertEqual(problems, [], "run: python -m simorgh.contracts.schemagen\n" + "\n".join(problems))

    def test_rendering_is_deterministic(self):
        self.assertEqual(schemagen.render_all(), schemagen.render_all())

    def test_every_rendered_schema_is_draft_2020_12_json(self):
        for name, text in schemagen.render_all().items():
            data = json.loads(text)
            self.assertIn("2020-12", data["$schema"], name)
            self.assertEqual(data["title"] + ".v1.json", name)

    def test_write_then_check_round_trips_and_removes_stale_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "stale.v1.json").write_text("{}")
            schemagen.write(directory)
            self.assertFalse((directory / "stale.v1.json").exists())
            self.assertEqual(schemagen.check(directory), [])
            (directory / "task.started.v1.json").write_text("{}")
            self.assertEqual(schemagen.check(directory), ["stale: task.started.v1.json"])

    def test_main_check_exit_codes(self):
        self.assertEqual(schemagen.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
