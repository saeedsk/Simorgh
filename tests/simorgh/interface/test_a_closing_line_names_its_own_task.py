"""A finished task is named again when somebody else's tree is open.

A branch and a corner carry no name: `⎿ ✅ completed in 88s` belongs to
whatever tree was drawn last. Live, 2026-09-22 at 19:49:59, a benchmark
case finished in the same SECOND the creator asked a question by voice,
and its patch summary was drawn under his question --

    ⏺ 💬 chat · voice · Hey Sim, what's the conversation history...
      ⎿  ✅ completed in 88s
         Fixed and committed (4b4409701). In `astropy/utils/introspection.py`...

-- so the screen said Sim had answered "what's the conversation history
with Said?" with a fix to an astropy version comparison. Reprinting the
root costs one line and is never wrong.
"""

import unittest
from types import SimpleNamespace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.interface.activity import TaskRecord
from simorgh.interface.config import Config
from simorgh.interface.service import Service


def _message(kind: str, task_id: str, **payload) -> Message:
    return Message.new(kind, source="test", payload={"task_id": task_id, **payload})


class AClosingLineNamesItsOwnTask(unittest.TestCase):
    def setUp(self):
        self.service = Service.__new__(Service)
        self.printed: list[str] = []
        self.service._out = self.printed.append            # noqa: SLF001
        self.service.config = Config(narrate=True, narrate_autonomous=True, narrate_steps=False)
        self.service._color = False                        # noqa: SLF001
        self.service._tree_owner = ""                      # noqa: SLF001
        self.service._live = SimpleNamespace(enabled=False)  # noqa: SLF001

    def _record(self, task_id: str, kind: str, topic: str) -> TaskRecord:
        record = TaskRecord(task_id=task_id, kind=kind, origin="benchmark", description=topic)
        record.status = "completed"
        record.started_at = None
        return record

    def test_an_ending_under_somebody_elses_tree_reprints_its_own_root(self):
        bench = self._record("0ee2cbd1", "patch", "swebench astropy-14963")
        self.service._tree_owner = "46276e80"              # noqa: SLF001 -- the chat turn's tree is open
        self.service._narrate_autonomous(                  # noqa: SLF001
            _message(topics.TASK_COMPLETED, "0ee2cbd1", result_summary="Fixed and committed."), bench)
        self.assertEqual(len(self.printed), 2, self.printed)
        self.assertIn("0ee2cbd1", self.printed[0], "the root names the task that is closing")
        self.assertIn("swebench astropy-14963", self.printed[0])
        self.assertIn("completed", self.printed[1])

    def test_a_tree_that_is_already_its_own_does_not_repeat_the_root(self):
        bench = self._record("0ee2cbd1", "patch", "swebench astropy-14963")
        self.service._tree_owner = "0ee2cbd1"              # noqa: SLF001
        self.service._narrate_autonomous(                  # noqa: SLF001
            _message(topics.TASK_COMPLETED, "0ee2cbd1", result_summary="Fixed and committed."), bench)
        self.assertEqual(len(self.printed), 1, "one corner, no second root")

    def test_starting_a_tree_claims_it(self):
        bench = self._record("0ee2cbd1", "patch", "swebench astropy-14963")
        self.service._narrate_autonomous(_message(topics.TASK_STARTED, "0ee2cbd1"), bench)  # noqa: SLF001
        self.assertEqual(self.service._tree_owner, "0ee2cbd1")  # noqa: SLF001

    def test_an_ending_releases_the_tree(self):
        bench = self._record("0ee2cbd1", "patch", "swebench astropy-14963")
        self.service._tree_owner = "0ee2cbd1"              # noqa: SLF001
        self.service._narrate_autonomous(                  # noqa: SLF001
            _message(topics.TASK_COMPLETED, "0ee2cbd1", result_summary="done"), bench)
        self.assertEqual(self.service._tree_owner, "", "the next line belongs to whoever draws it")  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
