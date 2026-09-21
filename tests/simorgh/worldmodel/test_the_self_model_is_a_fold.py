"""Stage 6 item 1: a restart keeps what Sim learnt about itself.

The module docstring of `selfmodel.py` has said, since it was
written, that mutations are "in-memory only for this session, not yet
a fold of a durable `self:model` Ledger stream across restarts" --
and left every mutator a pure function so that sentence could one day
be deleted. This is that day for the half that is history:
competence, limitations, the patches landed, the skills acquired.

Capabilities and goals are deliberately NOT replayed: the tool
registry announces itself at every boot and the task store is read,
so replaying them would recompute what is already known and could
resurrect a tool that has since gone.
"""

import unittest

from simorgh.contracts.envelope import Event
from simorgh.worldmodel.selfmodel import REPLAYABLE, build_static_model, replay


def _model(now: float = 1_790_000_000.0):
    from pathlib import Path

    return build_static_model(soul_path=Path("docs/SOUL.md"), clock_now=now,
                              areas=["memory", "voice"], continuity={"restarts": 1})


class EveryRecordedChangeReplays(unittest.TestCase):
    def test_competence_survives(self):
        model = replay(_model(), "competence",
                       {"task_type": "patch:memory", "success_rate": 0.62, "samples": 13}, now=1.0)
        self.assertEqual(model.competence["patch:memory"]["success_rate"], 0.62)
        self.assertEqual(model.competence["patch:memory"]["samples"], 13)

    def test_a_limitation_and_its_mitigation_both_replay(self):
        model = replay(_model(), "limitation",
                       {"text": "cannot read PDFs", "evidence": ["ledger:x"]}, now=1.0)
        self.assertTrue(any("PDF" in l["text"] for l in model.limitations))
        after = replay(model, "mitigate", {"subject": "cannot read PDFs"}, now=2.0)
        self.assertIsNotNone(after)

    def test_a_landed_patch_and_a_skill_replay(self):
        model = replay(_model(), "change",
                       {"kind": "self_patch", "subject": "simorgh/memory/store.py",
                        "commit": "abc1234", "summary": "persist vectors at store time"}, now=1.0)
        self.assertTrue(any(c.get("commit") == "abc1234" for c in model.change_history))
        model = replay(model, "skill", {"name": "unpack_zip", "tests": 3}, now=2.0)
        self.assertIn("unpack_zip", [s["name"] if isinstance(s, dict) else s
                                     for s in model.capabilities["skills"]])

    def test_an_unknown_rule_is_ignored_rather_than_fatal(self):
        """A stream written by a newer Sim must still load in an older
        one: the alternative is a boot that dies on its own history."""
        model = _model()
        self.assertIs(replay(model, "something_from_the_future", {"x": 1}, now=1.0), model)

    def test_the_replayable_set_is_history_and_not_a_derived_view(self):
        self.assertEqual(sorted(REPLAYABLE), ["change", "competence", "limitation", "mitigate", "skill"])
        for derived in ("capabilities", "goals", "tools", "areas", "restarts"):
            self.assertNotIn(derived, REPLAYABLE,
                             f"{derived} is re-derived at every boot; replaying it would resurrect stale facts")


class AWholeStreamFolds(unittest.TestCase):
    """What `_replay_self` does at boot, without a Kernel."""

    def _events(self):
        rows = [
            ("competence", {"task_type": "patch:memory", "success_rate": 0.62, "samples": 13}),
            ("limitation", {"text": "cannot read scanned PDFs", "evidence": []}),
            ("change", {"kind": "self_patch", "subject": "simorgh/voice/vad.py", "commit": "9005a6f",
                        "summary": "a quiet room made Sim deaf every other turn"}),
            ("skill", {"name": "unpack_zip", "tests": 3}),
        ]
        return [Event(stream="self:changes", type=rule, ts=100.0 + i, trace_id="self:changes",
                      causation_id=None, payload={"rule": rule, "args": args})
                for i, (rule, args) in enumerate(rows)]

    def test_the_model_after_a_restart_has_all_of_it(self):
        model = _model()
        for event in self._events():
            model = replay(model, event.payload["rule"], event.payload["args"], now=event.ts)
        self.assertEqual(model.competence["patch:memory"]["samples"], 13)
        self.assertTrue(model.limitations)
        self.assertTrue(model.change_history)
        self.assertTrue(model.capabilities["skills"])

    def test_folding_the_same_stream_twice_gives_the_same_model(self):
        """Determinism is the whole claim of a fold. Two boots on one
        stream must agree, or "the model is exactly the fold of this
        stream" is decoration."""
        first, second = _model(), _model()
        for event in self._events():
            first = replay(first, event.payload["rule"], event.payload["args"], now=event.ts)
        for event in self._events():
            second = replay(second, event.payload["rule"], event.payload["args"], now=event.ts)
        self.assertEqual(first.competence, second.competence)
        self.assertEqual(first.limitations, second.limitations)
        self.assertEqual(first.change_history, second.change_history)
        self.assertEqual(first.capabilities["skills"], second.capabilities["skills"])


if __name__ == "__main__":
    unittest.main()
