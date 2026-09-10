"""Which tests failed has to survive being cut twice.

`RunTestsTool` returns the TAIL of pytest's stdout
(`completed.stdout[-cap:]`); `orchestration/session.py` records the
step from the HEAD of that (`full[:_DETAIL_CHARS]`, 2000 chars) and
shows the model the first 8000. pytest prints the failing node ids only
in its short summary, at the very end. So for any run longer than the
cut -- which is every real run of this repo's suite -- the node ids
were in neither what the model saw nor what verification received.

That is not a cosmetic loss. `full_suite_ran` cannot attribute a suite
failure to the change under review without them, and a check that
cannot attribute has only one thing to say once the suite is red: run
it again. Both observers who watched a task burn its whole revision
budget against a red suite were watching that.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.contracts.pytestfailures import failing_nodeids, format_marker, hoist_marker, parse_marker
from simorgh.execution.config import Config
from simorgh.execution.tools import RunTestsTool

_DETAIL_CHARS = 2000  # orchestration/session.py::SessionRunner._DETAIL_CHARS


def _ctx(config: Config) -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=config.repo_root, clock=None, logger=None, ledger=None)


class TestTheMarkerSurvivesTruncation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
        # Noisy on purpose: this failure prints far more than the 2000
        # characters orchestration keeps from the head, so an unmarked
        # run would reach verification as a traceback and nothing else.
        (self.root / "tests" / "test_loud.py").write_text(
            "def test_loud():\n"
            "    payload = 'x' * 200\n"
            "    for _ in range(40):\n"
            "        print(payload)\n"
            "    assert False, payload\n"
        )
        self.config = Config(repo_root=self.root, test_timeout_s=60.0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_a_failing_run_names_its_failures_at_the_head(self) -> None:
        result = await RunTestsTool(self.config).run({"target": "tests"}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["failing_nodeids"], ["tests/test_loud.py::test_loud"])
        head = result.output[:_DETAIL_CHARS]
        self.assertGreater(len(result.output), _DETAIL_CHARS, "the fixture is not noisy enough to test this")
        self.assertEqual(parse_marker(head), ("tests/test_loud.py::test_loud",))

    async def test_a_passing_run_gets_no_marker(self) -> None:
        result = await RunTestsTool(self.config).run(
            {"target": "tests/test_ok.py"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.output)
        self.assertIsNone(parse_marker(result.output))
        self.assertEqual(result.metadata["failing_nodeids"], [])


class TestTheWireFormat(unittest.TestCase):
    def test_collection_errors_are_named_too(self) -> None:
        self.assertEqual(
            failing_nodeids("ERROR tests/a.py\nFAILED tests/b.py::test_c - AssertionError: x\n"),
            ("tests/a.py", "tests/b.py::test_c"),
        )

    def test_a_round_trip(self) -> None:
        ids = ("tests/a.py::test_b", "tests/c.py::TestD::test_e")
        self.assertEqual(parse_marker(f"[ran target='tests']\n{format_marker(ids)}\nnoise"), ids)

    def test_no_failures_means_no_marker_and_no_opinion(self) -> None:
        self.assertEqual(format_marker(()), "")
        self.assertIsNone(parse_marker("3 failed, 10 passed"))

    def test_a_capped_list_reads_back_as_unavailable(self) -> None:
        """The list is capped; the count is not. A reader that took a
        capped list for the whole truth would excuse 199 failures it
        never looked at."""
        self.assertIsNone(parse_marker("[failed 200: tests/a.py::test_b]"))


class TestTheStderrTailDoesNotBuryIt(unittest.TestCase):
    """Measured on a live trial, 2026-09-10: the marker landed at
    character 1535 of the step's 2000, and survived by 465 characters.

    `execution/service.py::_publish_result` puts up to 1500 characters
    of stderr into a failed result's `error`, and
    `orchestration/session.py` renders the step as
    `f"{error}\n\n{output}"` before cutting to 2000. pytest-asyncio
    prints a deprecation banner per xdist worker, so on this repo that
    1500-character allowance is always spent. One more worker and
    `full_suite_ran` would have been blind again -- with nothing in the
    record to say anything had been lost.
    """

    def test_the_marker_is_first_whatever_precedes_it(self) -> None:
        noisy = "exit_code=1\n" + ("PytestDeprecationWarning: blah blah. " * 60)
        step = f"{noisy}\n\n[failed 1: tests/a.py::test_b]\n" + ("." * 4000)
        self.assertGreater(step.find("[failed"), 2000)
        hoisted = hoist_marker(step)
        self.assertEqual(parse_marker(hoisted[:2000]), ("tests/a.py::test_b",))
        self.assertTrue(hoisted.startswith("[failed 1:"))

    def test_it_is_moved_not_copied(self) -> None:
        hoisted = hoist_marker("noise\n[failed 1: tests/a.py::test_b]\ntail")
        self.assertEqual(hoisted.count("[failed"), 1)
        self.assertIn("noise", hoisted)
        self.assertIn("tail", hoisted)

    def test_text_with_no_marker_is_untouched(self) -> None:
        self.assertEqual(hoist_marker("3 failed, 10 passed"), "3 failed, 10 passed")


if __name__ == "__main__":
    unittest.main()
