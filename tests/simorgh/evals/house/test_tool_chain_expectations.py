"""Stage 14 item 1: the tool-chain expectations, against hand-built records.

Each expectation is a pure function of the record, so the clearest
statement of what it means is a record built by hand with the messages
a real turn publishes (`action.proposed`, `action.result`, `task.started`,
`task.step`, `task.completed`) and the house's own log. Each one is
shown passing AND failing: an expectation that cannot fail is a line of
documentation pretending to be a test.
"""

import time
import unittest

from simorgh.contracts.envelope import Message
from simorgh.evals.house.record import Record
from simorgh.evals.house.script import (
    Beat, answered, called_any, called_in_order, called_with, containing, matches, recovered,
    steps_at_most, the_house_did, the_house_left,
)


def _record(*messages, house=()) -> tuple[Record, float]:
    record, since = Record(), time.monotonic()
    for topic, payload in messages:
        record.saw(Message.new(topic, source="test", payload=payload))
    for service, targets, data in house:
        record.house_did(service, targets, data)
    return record, since


def _proposed(tool, args=None, *, action_id="a1", task_id="t1"):
    return ("action.proposed", {"tool": tool, "args": dict(args or {}), "action_id": action_id,
                                "task_id": task_id})


def _turn(task_id="t1", *, steps=(), ended="task.completed", floor=False, failures=()):
    """A session that started, stepped, maybe had failing tools, and ended."""
    out = [("task.started", {"task_id": task_id})]
    for number in steps:
        out.append(("task.step", {"task_id": task_id, "step_no": number, "phase": "gather",
                                  "summary": "asking the model"}))
        out.append(("task.step", {"task_id": task_id, "step_no": number, "phase": "act",
                                  "summary": "a tool"}))
    for action_id in failures:
        out.append(_proposed("home_call", {"service": "light.turn_on"}, action_id=action_id,
                             task_id=task_id))
        out.append(("action.result", {"action_id": action_id, "ok": False, "tool": "home_call",
                                      "error": "refused: Home Assistant did not answer"}))
    if ended == "task.completed":
        out.append((ended, {"task_id": task_id, "result_summary": "done", **({"floor": True} if floor else {})}))
    elif ended:
        out.append((ended, {"task_id": task_id, "reason": "a tool failed", "terminal": True}))
    return out


class Matching(unittest.TestCase):
    def test_numbers_match_whatever_their_type(self):
        self.assertTrue(matches(21.5, "21.5"))
        self.assertTrue(matches(19, 19.0))
        self.assertFalse(matches(21.5, 21))
        self.assertFalse(matches(21.5, "warm"))

    def test_dicts_are_a_subset_and_may_arrive_as_json(self):
        self.assertTrue(matches({"temperature": 21}, {"temperature": 21.0, "hvac_mode": "heat"}))
        self.assertTrue(matches({"data": {"brightness": 128}}, {"data": '{"brightness": 128}'}))
        self.assertFalse(matches({"temperature": 21}, {"hvac_mode": "heat"}))

    def test_text_ignores_case_and_space_and_containing_finds_a_part(self):
        self.assertTrue(matches("light.turn_on", " Light.Turn_On "))
        self.assertFalse(matches("light.turn_on", "light.turn_off"))
        self.assertTrue(matches(containing("18:45"), "today at 18:45"))
        self.assertFalse(matches(containing("18:45"), "6:45pm"))


class CalledWith(unittest.TestCase):
    def test_a_subset_of_the_arguments_is_enough(self):
        record, since = _record(_proposed("home_call", {"service": "climate.set_temperature",
                                                        "target": "climate.hallway",
                                                        "data": {"temperature": 21.5}}))
        self.assertEqual(called_with("home_call", service="climate.set_temperature",
                                     data={"temperature": 21.5}).check(record, since), "")

    def test_the_wrong_value_fails_and_quotes_what_was_proposed(self):
        record, since = _record(_proposed("home_call", {"service": "climate.set_temperature",
                                                        "data": {"temperature": 21}}))
        why = called_with("home_call", data={"temperature": 21.5}).check(record, since)
        self.assertIn("21", why)
        self.assertIn("not", why)

    def test_a_tool_never_proposed_says_so(self):
        record, since = _record(_proposed("remind", {"when": "9pm"}))
        self.assertIn("never proposed", called_with("home_call").check(record, since))


class CalledInOrder(unittest.TestCase):
    def test_a_subsequence_with_other_tools_between(self):
        record, since = _record(_proposed("home_find"), _proposed("remember"), _proposed("home_call"))
        self.assertEqual(called_in_order("home_find", "home_call").check(record, since), "")

    def test_the_wrong_order_fails(self):
        record, since = _record(_proposed("home_call"), _proposed("home_state"))
        self.assertIn("home_call", called_in_order("home_state", "home_call").check(record, since))

    def test_a_tuple_is_any_one_of(self):
        record, since = _record(_proposed("home_describe"), _proposed("home_call"))
        expectation = called_in_order(("home_state", "home_describe"), "home_call")
        self.assertEqual(expectation.check(record, since), "")

    def test_the_same_tool_twice_needs_two_calls(self):
        once, since = _record(_proposed("home_call"))
        twice, since2 = _record(_proposed("home_call"), _proposed("home_call", action_id="a2"))
        self.assertNotEqual(called_in_order("home_call", "home_call").check(once, since), "")
        self.assertEqual(called_in_order("home_call", "home_call").check(twice, since2), "")

    def test_called_any(self):
        record, since = _record(_proposed("home_find"))
        self.assertEqual(called_any("home_state", "home_find").check(record, since), "")
        self.assertIn("none of", called_any("home_state").check(record, since))


class StepsAtMost(unittest.TestCase):
    def test_counts_steps_not_messages(self):
        # Two messages per step (the heads-up and the step itself) and
        # three steps: three, not six.
        record, since = _record(*_turn(steps=(1, 2, 3)))
        self.assertEqual(steps_at_most(3).check(record, since), "")
        self.assertIn("took 3 steps", steps_at_most(2).check(record, since))

    def test_only_the_beats_own_session(self):
        # A background task stepping meanwhile is not the turn's cost.
        record, since = _record(("percept.text.received", {"session_id": "t1", "text": "hi"}),
                                *_turn("t1", steps=(1,)), *_turn("other", steps=(1, 2, 3, 4)))
        self.assertEqual(steps_at_most(1).check(record, since), "")

    def test_no_session_is_not_a_pass(self):
        record, since = _record()
        self.assertIn("no session", steps_at_most(5).check(record, since))


class Recovered(unittest.TestCase):
    def test_a_failure_and_then_completed(self):
        record, since = _record(*_turn(steps=(1, 2), failures=("a1",)))
        self.assertEqual(recovered().check(record, since), "")

    def test_nothing_failed_is_not_a_recovery(self):
        record, since = _record(*_turn(steps=(1,)))
        self.assertIn("no tool failed", recovered().check(record, since))

    def test_a_session_that_failed_did_not_recover(self):
        record, since = _record(*_turn(steps=(1,), failures=("a1",), ended="task.failed"))
        self.assertIn("failed", recovered().check(record, since))

    def test_ending_on_the_floor_is_not_a_recovery(self):
        record, since = _record(*_turn(steps=(1,), failures=("a1",), floor=True))
        self.assertIn("floor", recovered().check(record, since))

    def test_never_ended(self):
        record, since = _record(*_turn(steps=(1,), failures=("a1",), ended=""))
        self.assertIn("never completed", recovered().check(record, since))


class TheHouse(unittest.TestCase):
    def test_the_house_did_with_data(self):
        record, since = _record(house=[("climate.set_temperature", ("climate.hallway",),
                                        {"temperature": 22.0})])
        self.assertEqual(the_house_did("climate.set_temperature", "climate.hallway",
                                       temperature=22).check(record, since), "")
        why = the_house_did("climate.set_temperature", "climate.hallway", temperature=21.5).check(record, since)
        self.assertIn("22", why)

    def test_the_house_did_without_data_keeps_its_name(self):
        # The name is what the observer clusters findings by.
        self.assertEqual(the_house_did("light.turn_on").name, "the house did light.turn_on")

    def test_the_house_left_one_device_alone(self):
        record, since = _record(house=[("light.turn_on", ("light.kitchen_main",), {})])
        self.assertEqual(the_house_left("light.living_room").check(record, since), "")
        self.assertIn("light.turn_on", the_house_left("light.kitchen_main").check(record, since))


class AnsweredAtTheConsole(unittest.TestCase):
    def test_a_completed_typed_turn_is_an_answer(self):
        record, since = _record(("turn.completed", {"channel": "cli", "text": "391."}))
        self.assertEqual(answered().check(record, since), "")

    def test_a_voice_turn_must_be_spoken(self):
        record, since = _record(("turn.completed", {"channel": "voice", "text": "391."}))
        self.assertEqual(answered().check(record, since), "Sim said nothing")

    def test_an_empty_or_cancelled_typed_turn_is_not(self):
        empty, since = _record(("turn.completed", {"channel": "cli", "text": "  "}))
        gone, since2 = _record(("turn.completed", {"channel": "cli", "text": "x", "cancelled": True}))
        self.assertNotEqual(answered().check(empty, since), "")
        self.assertNotEqual(answered().check(gone, since2), "")


class TheBeat(unittest.TestCase):
    def test_fails_and_answers_default_to_nothing(self):
        beat = Beat(says="hello")
        self.assertEqual((beat.fails, beat.answers), ({}, ""))


if __name__ == "__main__":
    unittest.main()
