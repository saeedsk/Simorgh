"""`simorgh/planning/reground.py` (07-planning.md section 5.5): the
staleness rule and the `STILL_VALID` answer parser, in isolation from
`Service`'s wiring (that end-to-end path is
`tests/simorgh/integration/test_reground_drift_flow.py`). Neither
`needs_check` nor `check` had any coverage before this file -- the
module existed but nothing called it, in tests or in `Service`.
"""

from __future__ import annotations

import unittest

from simorgh.planning.model import Task
from simorgh.planning.reground import check, needs_check

from tests.simorgh.orchestration.harness import run


def _child(created_at: float = 0.0) -> Task:
    return Task(
        id="c1", kind="patch", description="add retry jitter", subject="src/orchestrator/retry.py",
        parent_id="p1", created_at=created_at, updated_at=created_at,
    )


class _FakeCaller:
    def __init__(self, reply: str | None) -> None:
        self._reply = reply
        self.calls: list[dict] = []

    async def think(self, *, purpose: str, prompt: str, require_real_provider: bool = False) -> str | None:
        self.calls.append({"purpose": purpose, "prompt": prompt})
        return self._reply


class TestNeedsCheck(unittest.TestCase):
    def test_fresh_child_no_sibling_failure_does_not_need_check(self):
        self.assertFalse(needs_check(_child(created_at=100.0), now=100.5, regrounding_age_seconds=21600.0, sibling_failed_since=False))

    def test_child_older_than_regrounding_age_needs_check(self):
        self.assertTrue(needs_check(_child(created_at=0.0), now=21601.0, regrounding_age_seconds=21600.0, sibling_failed_since=False))

    def test_child_exactly_at_age_threshold_does_not_yet_need_check(self):
        # `>`, not `>=` -- 07-planning.md section 5.5's own wording is "older than".
        self.assertFalse(needs_check(_child(created_at=0.0), now=21600.0, regrounding_age_seconds=21600.0, sibling_failed_since=False))

    def test_sibling_failure_forces_a_check_regardless_of_age(self):
        self.assertTrue(needs_check(_child(created_at=100.0), now=100.5, regrounding_age_seconds=21600.0, sibling_failed_since=True))


class TestCheck(unittest.IsolatedAsyncioTestCase):
    @run
    async def test_still_valid_yes_is_parsed(self):
        caller = _FakeCaller("Nothing has changed.\nSTILL_VALID: yes\n")
        still_valid, reason = await check(caller, goal="ship the retry client", child=_child(), why="", changes_since=[])
        self.assertTrue(still_valid)
        self.assertEqual(reason, "")
        self.assertEqual(caller.calls[0]["purpose"], "reground")

    @run
    async def test_still_valid_no_with_suggested_revision_is_parsed(self):
        caller = _FakeCaller("STILL_VALID: no -- the client was already rewritten; drop this step.")
        still_valid, reason = await check(caller, goal="g", child=_child(), why="", changes_since=[])
        self.assertFalse(still_valid)
        self.assertIn("already rewritten", reason)

    @run
    async def test_narration_before_the_verdict_line_still_scans_every_line(self):
        # Same "scan every line for a verdict" rule Verification uses
        # (milestone 92) -- a rambling preamble must not defeat the answer.
        text = "Let me think about this carefully...\nActually, on reflection,\nSTILL_VALID: no -- scope changed.\n"
        caller = _FakeCaller(text)
        still_valid, _reason = await check(caller, goal="g", child=_child(), why="", changes_since=[])
        self.assertFalse(still_valid)

    @run
    async def test_no_provider_answer_is_not_evidence_of_drift(self):
        caller = _FakeCaller(None)
        still_valid, reason = await check(caller, goal="g", child=_child(), why="", changes_since=[])
        self.assertIsNone(still_valid)
        self.assertEqual(reason, "")

    @run
    async def test_a_non_answer_with_no_still_valid_line_is_not_evidence_of_drift(self):
        caller = _FakeCaller("I looked into it but I'm honestly not sure.")
        still_valid, reason = await check(caller, goal="g", child=_child(), why="", changes_since=[])
        self.assertIsNone(still_valid)
        self.assertEqual(reason, "")

    @run
    async def test_prompt_includes_goal_description_why_and_changes(self):
        caller = _FakeCaller("STILL_VALID: yes")
        await check(
            caller, goal="ship the retry client", child=_child(), why="unblocks the flaky test",
            changes_since=["sibling step failed: rewrite the HTTP client"],
        )
        prompt = caller.calls[0]["prompt"]
        self.assertIn("ship the retry client", prompt)
        self.assertIn("add retry jitter", prompt)
        self.assertIn("unblocks the flaky test", prompt)
        self.assertIn("sibling step failed", prompt)


if __name__ == "__main__":
    unittest.main()
