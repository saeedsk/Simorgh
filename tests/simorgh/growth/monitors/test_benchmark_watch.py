import asyncio
import unittest
from types import SimpleNamespace as NS

from simorgh.growth.monitors import benchmark_watch as bw


def _case(case_id, **kw):
    base = dict(case_id=case_id, correct=True, skipped=False, error="",
                blocked_by="", expected="4", answer="4")
    base.update(kw)
    return NS(**base)


class _Store:
    def __init__(self, records):
        self._records = records

    async def history(self, *, suite="", model="", limit=100):
        return self._records


class FailingCandidatesTestCase(unittest.TestCase):
    def test_only_scored_wrong_cases_become_candidates(self):
        record = NS(run_id="r1", suite="gaia", results=[
            _case("a"),
            _case("b", correct=False, answer="5"),
            _case("c", correct=False, skipped=True),
            _case("d", correct=False, error="timeout"),
        ])
        found = bw.failing_candidates([record])
        self.assertEqual([f["subject"] for f in found], ["gaia/b", "gaia/d"])
        self.assertEqual(found[0]["kind"], "patch")
        self.assertEqual(found[0]["failed_check"], "answer_correct")
        self.assertIn("got '5'", found[0]["reason"])
        self.assertEqual(found[1]["failed_check"], "case_ran")
        self.assertEqual(found[1]["reason"], "timeout")
        self.assertEqual(found[0]["evidence"], ["r1"])

    def test_blocked_case_names_what_stopped_it(self):
        record = NS(run_id="r2", suite="gaia", results=[
            _case("e", correct=False, blocked_by="verifier"),
        ])
        found = bw.failing_candidates([record])
        self.assertEqual(found[0]["failed_check"], "not_blocked:verifier")
        self.assertEqual(found[0]["reason"], "stopped by verifier")


class WatchTestCase(unittest.TestCase):
    def test_emits_only_to_growth_candidates(self):
        record = NS(run_id="r3", suite="gaia", results=[
            _case("x", correct=False), _case("y", correct=False),
        ])
        written = []

        async def append(stream, event_type, payload):
            written.append((stream, event_type, payload))

        found = asyncio.run(bw.watch(_Store([record]), append))
        self.assertEqual(len(found), 2)
        self.assertEqual({s for s, _, _ in written}, {"growth:candidates"})
        self.assertEqual({t for _, t, _ in written}, {"candidate"})
        self.assertEqual([p["subject"] for _, _, p in written], ["gaia/x", "gaia/y"])

    def test_no_failures_writes_nothing(self):
        record = NS(run_id="r4", suite="gaia", results=[_case("z")])
        written = []

        async def append(stream, event_type, payload):
            written.append(stream)

        self.assertEqual(asyncio.run(bw.watch(_Store([record]), append)), [])
        self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
