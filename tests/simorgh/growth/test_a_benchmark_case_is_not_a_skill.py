"""A benchmark case is not work worth keeping.

The creator's GAIA run of 2026-09-20 left eleven skill-writing tasks
queued behind it:

    simorgh_skills/what_was_volume_fish.py: Write a skill…
    simorgh_skills/video_https_www_l1vxcyzayym.py: Write a skill…

Each one a model call and a queue slot spent writing a function
nobody will ever call, one of them named after a YouTube id. A GAIA
question is a one-off chosen to be hard; a skill is for a job the
household will ask for again, and those are different things.
"""

import unittest

from simorgh.growth.monitors.distillation import NOT_WORTH_KEEPING, candidate_for

WORK = dict(kind="research", succeeded=True,
            description="how many bird species are on camera simultaneously",
            tools=["web_fetch", "read_file", "run_shell"])


class WhoseTasksBecomeSkills(unittest.TestCase):
    def test_a_persons_research_still_does(self):
        self.assertIsNotNone(candidate_for(origin="human", **WORK))

    def test_a_benchmark_case_does_not(self):
        self.assertIsNone(candidate_for(origin="benchmark", **WORK))

    def test_benchmark_is_the_origin_that_is_excluded(self):
        self.assertIn("benchmark", NOT_WORTH_KEEPING)

    def test_an_unknown_origin_is_treated_as_ordinary_work(self):
        """Older records carry no origin, and silently refusing to
        learn from all of them would be worse than the waste."""
        self.assertIsNotNone(candidate_for(**WORK))
        self.assertIsNotNone(candidate_for(origin="", **WORK))

    def test_the_other_gates_still_apply(self):
        self.assertIsNone(candidate_for(origin="human", **{**WORK, "succeeded": False}))
        self.assertIsNone(candidate_for(origin="human", **{**WORK, "tools": ["read_file"]}))


class TheMonitorPassesItOn(unittest.TestCase):
    def test_task_meta_carries_the_origin(self):
        """The filter is useless if `_on_task_created` drops it."""
        from simorgh.growth.monitors.service import _TaskMeta

        self.assertEqual(_TaskMeta().origin, "")
        self.assertEqual(_TaskMeta(origin="benchmark").origin, "benchmark")


if __name__ == "__main__":
    unittest.main()
