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
from simorgh.contracts.pytestfailures import (
    failing_nodeids,
    format_marker,
    hoist_marker,
    marker_for,
    parse_marker,
    reported_failures,
)
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


class TestANodeIdTheParserCannotRead(unittest.IsolatedAsyncioTestCase):
    """A list that lost an id must not read back as a complete, shorter one.

    Both halves of this were live in the first version of the marker,
    and both were found by running pytest and reading what it actually
    printed (observer, 2026-09-10):

    * `test_p[hello world]` -- a parametrized id with a SPACE in it, which
      `@pytest.mark.parametrize("x", ["hello world"])` produces -- matched
      the summary-line pattern not at all. Three tests failed, the marker
      named two, and `full_suite_ran` would have read that as the whole
      truth: attribute the two, find they also fail at the base revision,
      and PASS a change that had broken the third. A false pass, in the
      one check written to make false passes impossible.
    * `parse_marker` ended the marker at its first `]`, and nearly every
      parametrized node id ends in one, so `[failed 2: a::test_p[plain]
      b::test_y]` parsed as one id against a count of two and read back as
      "unattributable". Attribution therefore switched itself off whenever
      a parametrized test was among the failures -- and the budget burn
      against a red suite that it exists to stop came back with it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_params.py").write_text(
            "import pytest\n\n"
            "@pytest.mark.parametrize('x', ['hello world', 'plain'])\n"
            "def test_p(x):\n"
            "    assert False\n\n"
            "def test_normal():\n"
            "    assert False\n"
        )
        self.config = Config(repo_root=self.root, test_timeout_s=60.0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_a_run_whose_ids_cannot_all_be_written_is_unattributable(self) -> None:
        result = await RunTestsTool(self.config).run({"target": "tests"}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        # Every failure is named -- the spaced one included, so nothing
        # is hidden from the model reading the output...
        self.assertIn("test_p[hello world]", result.output)
        # ...and because a space-separated list cannot carry it back,
        # the mechanical reader is told it cannot attribute this run
        # rather than handed two of three failures as though they were all.
        self.assertIsNone(parse_marker(result.output))

    def test_a_spaced_id_is_parsed_not_skipped(self) -> None:
        output = ("FAILED tests/a.py::test_p[hello world] - assert False\n"
                  "FAILED tests/a.py::test_normal - assert False\n"
                  "2 failed in 0.02s\n")
        self.assertEqual(failing_nodeids(output),
                         ("tests/a.py::test_p[hello world]", "tests/a.py::test_normal"))

    def test_the_count_is_pytests_own_not_the_parsers(self) -> None:
        # One summary line this module cannot read: pytest says three,
        # the parser found two, and the marker says three so it reads
        # back as unattributable.
        output = ("FAILED tests/a.py::test_b - assert False\n"
                  "FAILED tests/a.py::test_c - assert False\n"
                  "3 failed in 0.02s\n")
        self.assertEqual(reported_failures(output), 3)
        self.assertIsNone(parse_marker(marker_for(output)))

    def test_a_full_list_still_reads_back(self) -> None:
        output = ("FAILED tests/a.py::test_b - assert False\n"
                  "FAILED tests/a.py::test_c - assert False\n"
                  "2 failed, 5 passed in 0.02s\n")
        self.assertEqual(parse_marker(marker_for(output)),
                         ("tests/a.py::test_b", "tests/a.py::test_c"))

    def test_one_test_named_twice_is_not_mistaken_for_a_lost_one(self) -> None:
        # A test that fails and then errors in its own teardown prints
        # two summary lines for one id and pytest counts both. Deduping
        # them is right, and must not read as a missing id.
        output = ("FAILED tests/a.py::test_b - assert False\n"
                  "ERROR tests/a.py::test_b - RuntimeError: teardown\n"
                  "1 failed, 1 error in 0.02s\n")
        self.assertEqual(parse_marker(marker_for(output)), ("tests/a.py::test_b",))

    def test_a_parametrized_id_survives_the_round_trip(self) -> None:
        ids = ("tests/a.py::test_p[plain]", "tests/b.py::test_y")
        self.assertEqual(parse_marker(f"[ran target='tests']\n{format_marker(ids)}\nnoise"), ids)
        hoisted = hoist_marker("noise\n" + format_marker(ids) + "\ntail")
        self.assertEqual(parse_marker(hoisted), ids)


if __name__ == "__main__":
    unittest.main()
