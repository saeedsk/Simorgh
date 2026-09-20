"""Stage 11 item 8: a turn, decomposed.

The creator asked on 2026-09-20 why a reply took twenty seconds, and
the honest answer at the time was "part of it is my thinking step" --
a guess, because nothing broke a turn into pieces. These are the
pieces, and every one of them is a difference between two things
already on the bus, so the table cannot drift away from what happened.
"""

import unittest

from simorgh.evals.house.record import Record
from simorgh.evals.house.timing import BUDGETS_S, Table, Turn, from_record


class ATurnsSegments(unittest.TestCase):
    def test_a_segment_over_its_budget_is_named(self):
        turn = Turn("x", hear=0.5, think=3.0, first_audio=1.0, reply=4.0)
        self.assertEqual(turn.over(), ["think"])

    def test_a_segment_that_never_happened_is_not_a_breach(self):
        """Sim staying quiet is not Sim being slow."""
        self.assertEqual(Turn("x").over(), [])

    def test_every_segment_has_a_budget(self):
        turn = Turn("x", hear=0.0, think=0.0, first_audio=0.0, reply=0.0)
        for name in ("hear", "think", "first_audio", "reply"):
            self.assertIn(name, BUDGETS_S, name)
            self.assertIsNotNone(getattr(turn, name))


class TheTable(unittest.TestCase):
    def setUp(self):
        self.table = Table()
        for think in (0.2, 0.3, 4.0):
            self.table.add(Turn("x", hear=0.1, think=think, first_audio=think + 0.1, reply=think + 0.2))

    def test_percentiles_come_from_the_turns_that_have_the_segment(self):
        self.assertEqual(self.table.percentile("think", 0.5), 0.3)
        self.assertEqual(self.table.percentile("think", 0.95), 4.0)

    def test_a_segment_nothing_measured_is_none_not_zero(self):
        self.assertIsNone(Table().percentile("think"))

    def test_the_worst_segment_is_where_an_evening_should_go(self):
        self.assertEqual(self.table.worst_segment, "think")

    def test_it_renders_something_a_person_can_act_on(self):
        rendered = self.table.render()
        self.assertIn("budget", rendered)
        self.assertIn("think", rendered)
        self.assertIn("most often breaks its budget", rendered)

    def test_no_turns_says_so_rather_than_printing_an_empty_table(self):
        self.assertIn("no turns", Table().render())


class MeasuredFromWhenSomebodySpoke(unittest.TestCase):
    """Not from the percept. A percept appears only after VAD, the
    recogniser and the speaker book have all run, so measuring from it
    hides the entire listening path -- which is exactly where stage 3's
    two-second STT budget lives."""

    def _record(self):
        from simorgh.contracts.envelope import Message

        record = Record()
        mark = record.somebody_spoke("Mara", "Sim, are you there?", in_the_room=True)
        record.saw(Message.new("percept.text.received", source="voice",
                               payload={"speaker": "Mara", "text": "Sim, are you there?"}))
        record.saw(Message.new("cognition.think", source="orchestration", payload={"messages": []}))
        record.sim_spoke("Yes?")
        record.saw(Message.new("turn.completed", source="orchestration", payload={"text": "Yes?"}))
        return record, mark

    def test_every_segment_is_measured_and_ordered(self):
        record, _mark = self._record()
        table = from_record(record)
        self.assertEqual(len(table.turns), 1)
        turn = table.turns[0]
        for name in ("hear", "think", "first_audio", "reply"):
            self.assertIsNotNone(getattr(turn, name), name)
        self.assertLessEqual(turn.hear, turn.think)
        self.assertLessEqual(turn.first_audio, turn.reply)

    def test_a_beat_nobody_answered_still_appears(self):
        """A turn Sim ignored is a row with nothing after `hear`, not a
        missing row: how often Sim stays quiet is worth seeing."""
        record = Record()
        record.somebody_spoke("Mara", "an aside", in_the_room=True)
        table = from_record(record)
        self.assertEqual(len(table.turns), 1)
        self.assertIsNone(table.turns[0].reply)

    def test_turns_do_not_borrow_each_others_events(self):
        from simorgh.contracts.envelope import Message

        record = Record()
        record.somebody_spoke("Mara", "first", in_the_room=True)
        record.somebody_spoke("Mara", "second", in_the_room=True)
        record.saw(Message.new("turn.completed", source="orchestration", payload={}))
        table = from_record(record)
        self.assertIsNone(table.turns[0].reply, "the first beat was never answered")
        self.assertIsNotNone(table.turns[1].reply)


if __name__ == "__main__":
    unittest.main()
