"""What Sim DID, not just what was said (orchestration/worker.py).

`memory:procedural` had never held a single record on the creator's
machine. Its only writer was skill acquisition, which fires when Sim
writes itself a new tool and never had -- so the one kind of memory meant
to answer "how did I do this last time" was empty, while 2,422 episodic
transcripts answered "what was said" (2026-09-16).
"""

from __future__ import annotations

import types
import unittest

from simorgh.orchestration.worker import procedure_from


def _step(tool, ok=True, phase="act"):
    return types.SimpleNamespace(no=1, phase=phase, summary="", tool=tool, ok=ok)


def _session(steps, user_text="turn the spotlights off"):
    """Shaped like the real `Session` (orchestration/api.py): the task
    text is `user_text`. An earlier version of this fixture invented a
    `description` field, so it tested the same wrong assumption the code
    made and passed while the real path fell through to the summary."""
    return types.SimpleNamespace(task_id="t1", user_text=user_text, steps=steps)


def _outcome(kind="completed", result_summary="done"):
    return types.SimpleNamespace(kind=kind, result_summary=result_summary)


class WhatCountsAsAProcedure(unittest.TestCase):
    def test_a_finished_task_records_the_tools_in_order(self):
        said = procedure_from(_session([_step("cam_list"), _step("cam_light"), _step("cam_state")]), _outcome())
        self.assertEqual(said, "To turn the spotlights off: cam_list -> cam_light -> cam_state")

    def test_a_repeated_tool_is_one_move(self):
        """Eight `cam_light` calls in a row is 'switch the lights', not
        eight different things to do next time."""
        said = procedure_from(_session([_step("cam_list"), _step("cam_light"), _step("cam_light"),
                                        _step("cam_light"), _step("git_commit")]), _outcome())
        self.assertEqual(said, "To turn the spotlights off: cam_list -> cam_light -> git_commit")

    def test_a_step_that_failed_is_not_part_of_the_recipe(self):
        said = procedure_from(_session([_step("cam_list"), _step("cam_siren", ok=False), _step("cam_light")]),
                              _outcome())
        self.assertNotIn("cam_siren", said)
        self.assertEqual(said, "To turn the spotlights off: cam_list -> cam_light")

    def test_an_unfinished_task_is_not_a_procedure(self):
        for kind in ("failed", "blocked", "paused"):
            self.assertEqual(procedure_from(_session([_step("a"), _step("b")]), _outcome(kind=kind)), "",
                             f"{kind} is not how to do it")

    def test_a_turn_that_used_no_tools_writes_nothing(self):
        """Every chat turn completes. A 'procedure' with nothing in it is
        how episodic memory reached 2,422 records."""
        self.assertEqual(procedure_from(_session([]), _outcome()), "")
        self.assertEqual(procedure_from(_session([_step(None), _step(None)]), _outcome()), "")

    def test_one_tool_call_is_not_a_procedure_either(self):
        self.assertEqual(procedure_from(_session([_step("cam_light")]), _outcome()), "")

    def test_it_falls_back_to_the_summary_when_the_task_text_is_empty(self):
        session = _session([_step("a"), _step("b")], user_text="")
        self.assertTrue(procedure_from(session, _outcome(result_summary="fixed the gate")).startswith(
            "To fixed the gate:"))

    def test_a_very_long_description_is_bounded(self):
        session = _session([_step("a"), _step("b")], user_text="x" * 500)
        self.assertLess(len(procedure_from(session, _outcome())), 260)


class AgainstTheRealSession(unittest.TestCase):
    """Built from `orchestration.api.Session` itself, not a stand-in.

    The first version of this file invented a `description` field. The
    code read the same invented field, so the tests agreed with the bug
    and every real procedure quietly fell back to the result summary. A
    fake shaped by the same assumption cannot catch that; the real
    dataclass can, because it raises on a field it does not have.
    """

    def _real_session(self, steps, user_text="turn the spotlights off"):
        from simorgh.orchestration.api import Session
        from simorgh.orchestration.profiles import BY_KIND

        # A real profile too, rather than a second invented shape: the
        # one the chat kind actually runs with.
        return Session(task_id="t1", kind="chat", mode="execute",
                       profile=BY_KIND["chat"], user_text=user_text, steps=steps)

    def test_the_task_text_comes_off_a_real_session(self):
        session = self._real_session([_step("cam_list"), _step("cam_light")])
        self.assertEqual(procedure_from(session, _outcome()),
                         "To turn the spotlights off: cam_list -> cam_light")

    def test_a_real_session_has_no_description_field(self):
        from simorgh.orchestration.api import Session

        self.assertNotIn("description", Session.__dataclass_fields__)
        self.assertIn("user_text", Session.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
