"""A mined failure RATE asks for the cause; it does not edit code.

The creator, 2026-09-22, looking at six queued reflection tasks: "I
don't like the fact sim is scheduling nonsense, if it continues that
path, after a while this code base will be full of uncontrolled source
code."

He was reading tasks like "'patch' tasks failed 4/4 recent outcomes
(100%) -- worth reviewing for a systematic issue", which `intake` turned
into a `patch` task with NO scope: a percentage bought a licence to edit
any file in the repository. Worse, that 4/4 was four SWE-bench cases,
some failing on harness bugs -- a measurement, not Sim's work going
wrong.

The route from an observation to code already exists and is the careful
one: a research finding with a NAMED subject becomes a patch scoped to
that subject (`on_research_follow_up`). A pattern now goes in that door.
"""

from __future__ import annotations

import unittest

from tests.simorgh.planning.test_intake import _intake, run

PATTERN = {
    "kind": "failure_rate", "rate": 1.0, "task_type": "patch",
    "proposal": "'patch' tasks failed 4/4 recent outcomes (100%) -- worth reviewing for a systematic issue.",
}


class AStatisticDoesNotBuyACodeEdit(unittest.TestCase):
    @run
    async def test_a_mined_pattern_investigates_rather_than_patches(self):
        intake, _store = await _intake()
        created = await intake.on_patterns_found(patterns=[PATTERN])
        self.assertEqual(len(created), 1)
        task = created[0]
        self.assertEqual(task.kind, "research", "a rate says something is wrong, not what to change")
        self.assertIn("do not change any code", task.description)
        self.assertIn("failed 4/4", task.description, "the observation itself is kept")

    @run
    async def test_the_route_to_code_still_exists_and_is_scoped(self):
        """A finding that names a file becomes a patch confined to it."""
        intake, _store = await _intake()
        task = await intake.on_research_follow_up(
            research_task_id="r1", subject="simorgh/planning/scheduler.py",
            description="dispatch_ready counts unofferable work",
        )
        self.assertIsNotNone(task)
        self.assertEqual(task.kind, "patch")
        self.assertEqual(task.scope.paths, ("simorgh/planning/scheduler.py",))

    @run
    async def test_two_patterns_about_different_things_are_still_two_tasks(self):
        intake, _store = await _intake()
        other = {**PATTERN, "task_type": "research",
                 "proposal": "'research' tasks failed 6/7 recent outcomes (86%) -- worth reviewing for a systematic issue."}
        created = await intake.on_patterns_found(patterns=[PATTERN, other])
        self.assertEqual(len(created), 2, "the shared instructions must not collapse distinct findings")

    @run
    async def test_the_same_pattern_next_window_is_still_one_task(self):
        intake, _store = await _intake()
        self.assertEqual(len(await intake.on_patterns_found(patterns=[PATTERN])), 1)
        self.assertEqual(await intake.on_patterns_found(patterns=[PATTERN]), [],
                         "re-mining the same rate must not queue it twice")


if __name__ == "__main__":
    unittest.main()
