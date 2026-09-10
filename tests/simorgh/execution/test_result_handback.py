"""What a tool reports ABOUT its result, and what it does with data too
big to read inline (`execution/service.py::_store_rows`,
`_publish_result`'s `metadata_ref`).

Before 2026-09-09 a `ToolResult.metadata` was dropped on the floor
except for a handful of hand-picked fields, and a tool that fetched 200
rows could only ever render a summary of the first few -- the rows
themselves existed nowhere the model or a script could reach. The
comparables analysis another agent ran over 95120 listings needs the
data, not the summary.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.service import Service, metadata_for_blob


class _Logger:
    def warning(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


class _Ctx:
    def __init__(self):
        self.logger = _Logger()


class _Result:
    def __init__(self, metadata=None, output=""):
        self.metadata = metadata or {}
        self.output = output


class StoreRowsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _service(self, **config):
        settings = {"repo_root": self.root}
        settings.update(config)
        service = Service(config=Config(**settings))
        service._ctx = _Ctx()
        return service

    def test_rows_are_written_to_a_file_named_in_the_output(self):
        service = self._service()
        rows = [{"address": f"{i} Main St", "price": 1000 * i} for i in range(3)]
        output = service._store_rows("a1", _Result({"rows": rows}), "3 listings")
        self.assertIn("results/a1.json", output)
        self.assertIn("3 rows", output)
        written = json.loads((self.root / "results" / "a1.json").read_text())
        self.assertEqual(written, rows)

    def test_the_written_file_is_readable_through_read_file(self):
        # `results` is a readable root, so the model can open what it
        # just fetched -- that is the whole point of writing it.
        from simorgh.execution import pathsafety

        service = self._service()
        service._store_rows("a2", _Result({"rows": [{"x": 1}]}), "out")
        text = pathsafety.safe_read_file(
            self.root, "results/a2.json", readable_roots=Config().readable_roots)
        self.assertIn('"x"', text)
        self.assertNotIn("refused", text)

    def test_results_is_readable_but_not_a_write_scope(self):
        # Sim can read the data it fetched; it cannot commit it.
        config = Config()
        self.assertIn("results", config.readable_roots)
        self.assertNotIn("results/", config.write_scopes_source)

    def test_rows_beyond_the_cap_are_dropped_and_the_count_is_honest(self):
        service = self._service(results_max_rows=2)
        rows = [{"i": i} for i in range(5)]
        output = service._store_rows("a3", _Result({"rows": rows}), "out")
        self.assertIn("2 of 5 rows", output)
        self.assertEqual(len(json.loads((self.root / "results" / "a3.json").read_text())), 2)

    def test_a_tool_with_no_rows_is_untouched(self):
        service = self._service()
        self.assertEqual(service._store_rows("a4", _Result({"count": 3}), "out"), "out")
        self.assertFalse((self.root / "results").exists())

    def test_an_empty_row_list_writes_nothing(self):
        service = self._service()
        self.assertEqual(service._store_rows("a5", _Result({"rows": []}), "out"), "out")

    def test_an_unwritable_directory_is_not_fatal(self):
        # A data tool must not fail because a directory was not
        # writable: the rendered output is still a real answer.
        service = self._service(results_dir="results")
        (self.root / "results").write_text("i am a file, not a directory")
        self.assertEqual(service._store_rows("a6", _Result({"rows": [{"x": 1}]}), "out"), "out")

    def test_old_result_files_are_pruned(self):
        service = self._service(results_keep_files=3)
        for i in range(6):
            service._store_rows(f"act{i}", _Result({"rows": [{"i": i}]}), "out")
        remaining = list((self.root / "results").glob("*.json"))
        self.assertEqual(len(remaining), 3)

    def test_non_serialisable_values_do_not_crash_the_write(self):
        service = self._service()
        output = service._store_rows("a7", _Result({"rows": [{"when": object()}]}), "out")
        self.assertIn("results/a7.json", output)


class ListingsRowsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_search_listings_hands_back_every_match_not_just_the_rendered_page(self):
        from tests.simorgh.execution.test_realestate import ROWS, _ctx, _scraper

        from simorgh.execution.realestate import RealEstateListingsTool

        tool = RealEstateListingsTool(
            Config(repo_root=Path.cwd(), real_estate_max_results=1), scraper=_scraper())
        result = await tool.run({"location": "San Jose, CA"}, ctx=_ctx())
        self.assertEqual(result.metadata["returned"], 1)  # one rendered
        self.assertEqual(len(result.metadata["rows"]), len(ROWS))  # all handed back
        self.assertEqual(result.metadata["rows"][0]["address"], "20791 Via Corta")


class MetadataBlobTestCase(unittest.TestCase):
    """W21-07: `results_max_rows` capped the results FILE while the same
    uncapped list went into the Ledger blob beside it."""

    def test_the_row_list_becomes_a_pointer_not_a_second_copy(self):
        meta = metadata_for_blob({"rows": [{"i": i} for i in range(900)], "count": 900})
        self.assertEqual(meta["rows"], "<900 rows -- see the results file named in the output>")
        self.assertEqual(meta["count"], 900)

    def test_everything_that_is_not_rows_survives_untouched(self):
        original = {"url": "https://x", "sha256": "ab", "low_confidence": True}
        self.assertEqual(metadata_for_blob(original), original)

    def test_the_callers_metadata_is_not_mutated(self):
        original = {"rows": [{"i": 1}]}
        metadata_for_blob(original)
        self.assertEqual(original["rows"], [{"i": 1}])

    def test_a_non_list_rows_value_is_left_alone(self):
        self.assertEqual(metadata_for_blob({"rows": 5})["rows"], 5)
