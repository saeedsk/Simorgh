"""Stage 4 item 1: sessions, turns and blocks."""

import json
import unittest

from simorgh.contracts import session as s
from simorgh.contracts.streamnames import writers_for


class TurnsAndBlocks(unittest.TestCase):
    def _turns(self):
        return [
            s.Turn(0, "user", (s.Text("read a.py"),), ts=1.0),
            s.Turn(1, "assistant", (s.Text("Let me look."), s.ToolUse("c1", "read_file", {"path": "a.py"})), ts=2.0,
                   meta={"provider": "together", "in_tokens": 10, "out_tokens": 5, "cost": 0.0001}),
            s.Turn(2, "tool", (s.ToolResult("c1", "print(1)", bytes_total=8),), ts=3.0),
            s.Turn(3, "assistant", (s.Text("It prints 1."),), ts=4.0),
        ]

    def test_a_turn_round_trips_through_json(self):
        for turn in self._turns():
            back = s.turn_from_dict(json.loads(json.dumps(s.turn_to_dict(turn))))
            self.assertEqual(back, turn)

    def test_a_valid_transcript_has_no_problems(self):
        turns = self._turns()
        self.assertEqual([p for t in turns for p in s.validate_turn(t)], [])
        self.assertEqual(s.validate_pairs(turns), [])

    def test_the_rules(self):
        self.assertTrue(s.validate_turn(s.Turn(0, "robot")))
        self.assertTrue(s.validate_turn(s.Turn(0, "user", (s.ToolUse("c1", "x"),))))
        self.assertTrue(s.validate_turn(s.Turn(0, "tool", (s.Text("hi"),))))
        self.assertTrue(s.validate_turn(s.Turn(0, "assistant", (s.ToolUse("", "x"),))))
        self.assertTrue(s.validate_pairs([s.Turn(0, "tool", (s.ToolResult("nope", "x"),))]))
        with self.assertRaises(ValueError):
            s.block_from_dict({"kind": "video"})

    def test_a_session_round_trips_and_is_checked(self):
        session = s.Session("abc", "chat", channel="voice", person_id="ira", budget=s.Budget(turns=40, usd=0.5))
        self.assertEqual(s.session_from_dict(json.loads(json.dumps(s.session_to_dict(session)))), session)
        self.assertEqual(s.validate_session(session), [])
        self.assertTrue(s.validate_session(s.Session("x", "chat", depth=1)))
        self.assertTrue(s.validate_session(s.Session("x", "chat", state="gone")))

    def test_the_stream_is_named_and_owned(self):
        self.assertEqual(s.stream_name("abc"), "session:abc")
        self.assertEqual(writers_for("session:abc"), frozenset({"orchestration"}))
