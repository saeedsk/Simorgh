"""A question about a file needs the file.

GAIA asks things like "what is the oldest Blu-Ray in this spreadsheet".
38 of its 165 cases carry a file, and the harness used to skip every one
of them: the rows name a file, nothing fetched it, and a fifth of the
suite was unreachable by construction. The 2026-09-10 run skipped 11 of
53 cases for this reason alone.

Skipping was the honest thing to do while the file was missing -- a
question about a spreadsheet nobody downloaded is unanswerable, and
scoring it wrong would have been a lie about the model. Fetching it is
better than being honest about not fetching it.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from simorgh.benchmark import datasets
from simorgh.benchmark.api import Case
from simorgh.benchmark.config import Config
from simorgh.benchmark.runner import Runner

GAIA = datasets.SOURCES["gaia"]


def _case(**fields) -> Case:
    base = dict(id="32102e3e", question="what is the oldest Blu-Ray?", answer="Time-Parking 2",
                suite="gaia", attachment="sheet.xlsx",
                data=json.dumps({"file_path": "2023/validation/sheet.xlsx"}))
    base.update(fields)
    return Case(**base)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FetchAttachmentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(__import__("tempfile").mkdtemp())

    def test_the_file_is_written_where_the_case_can_read_it(self):
        with mock.patch.object(datasets.urllib.request, "urlopen",
                               return_value=_Response(b"spreadsheet bytes")) as opened:
            path, problem = datasets.fetch_attachment(GAIA, _case(), dest=self._dir, token="t")
        self.assertEqual(problem, "")
        self.assertEqual(path.read_bytes(), b"spreadsheet bytes")
        url = opened.call_args[0][0].full_url
        self.assertIn("gaia-benchmark/GAIA/resolve/main/2023/validation/sheet.xlsx", url)

    def test_the_local_copy_is_not_world_readable(self):
        """GAIA's terms forbid resharing the set; the row cache is 0600
        for the same reason."""
        with mock.patch.object(datasets.urllib.request, "urlopen", return_value=_Response(b"x")):
            path, _ = datasets.fetch_attachment(GAIA, _case(), dest=self._dir, token="t")
        self.assertEqual(oct(path.stat().st_mode)[-3:], "600")

    def test_a_file_already_fetched_is_not_fetched_again(self):
        with mock.patch.object(datasets.urllib.request, "urlopen", return_value=_Response(b"x")):
            datasets.fetch_attachment(GAIA, _case(), dest=self._dir, token="t")
        with mock.patch.object(datasets.urllib.request, "urlopen") as opened:
            path, problem = datasets.fetch_attachment(GAIA, _case(), dest=self._dir, token="t")
        opened.assert_not_called()
        self.assertEqual((problem, path.name), ("", "sheet.xlsx"))

    def test_a_case_from_an_older_cache_says_to_reload_the_suite(self):
        path, problem = datasets.fetch_attachment(GAIA, _case(data=""), dest=self._dir, token="t")
        self.assertIsNone(path)
        self.assertIn("benchmark load gaia", problem)

    def test_a_gated_suite_without_a_token_says_so(self):
        path, problem = datasets.fetch_attachment(GAIA, _case(), dest=self._dir, token="")
        self.assertIsNone(path)
        self.assertIn("HF_TOKEN", problem)

    def test_an_http_failure_is_reported_not_raised(self):
        error = datasets.urllib.error.HTTPError("u", 404, "gone", None, None)
        with mock.patch.object(datasets.urllib.request, "urlopen", side_effect=error):
            path, problem = datasets.fetch_attachment(GAIA, _case(), dest=self._dir, token="t")
        self.assertIsNone(path)
        self.assertIn("404", problem)

    def test_an_empty_body_is_a_failure_not_an_empty_file(self):
        with mock.patch.object(datasets.urllib.request, "urlopen", return_value=_Response(b"")):
            path, problem = datasets.fetch_attachment(GAIA, _case(), dest=self._dir, token="t")
        self.assertIsNone(path)
        self.assertIn("empty", problem)


class RunnerAttachmentTestCase(unittest.IsolatedAsyncioTestCase):
    def _runner(self, root: Path) -> Runner:
        return Runner(mock.MagicMock(), config=Config(), repo_root=root)

    async def test_the_case_is_asked_with_a_path_the_file_tools_can_open(self):
        root = Path(__import__("tempfile").mkdtemp())
        runner = self._runner(root)
        with mock.patch.object(datasets.urllib.request, "urlopen",
                               return_value=_Response(b"bytes")), \
                mock.patch.dict("os.environ", {"HF_TOKEN": "t"}):
            path, problem = await runner._fetch_attachment(_case())  # noqa: SLF001
        self.assertEqual(problem, "")
        # Repo-relative and under the workspace: the one directory the
        # file tools may both read and write.
        self.assertTrue(path.startswith("workspace/benchmark/"))
        self.assertTrue((root / path).is_file())
        self.assertIn(path, runner.prompt(_case(), path))

    async def test_a_case_whose_file_will_not_come_is_skipped_not_failed(self):
        root = Path(__import__("tempfile").mkdtemp())
        runner = self._runner(root)
        with mock.patch.object(datasets, "fetch_attachment", return_value=(None, "HTTP 403")):
            result = await runner.run_case(_case())
        self.assertTrue(result.skipped)
        self.assertFalse(result.correct)
        self.assertIn("sheet.xlsx", result.error)
        self.assertIn("403", result.error)


if __name__ == "__main__":
    unittest.main()
