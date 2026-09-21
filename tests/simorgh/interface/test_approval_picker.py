"""Answering an approval with the arrow keys.

The creator, 2026-09-20: the question and its options belong in the
prompt section as bullets you move through with the arrows, mark with
space, and send with Enter -- then a second question in the same
place showing what you picked, confirm or redo.

An approval is not a menu, and these are the tests that say so.
"""

import unittest

from simorgh.interface.picker import (
    CHOOSING, CONFIRMING, DONE, Picker, REDO, SOMETHING_ELSE, SUBMIT, TYPING,
)


def _picker(**over):
    payload = {"question": "Approve notify (body=Backyard Door Left)?",
               "options": ["yes", "no"], "prompt_id": "p1", **over}
    return Picker.for_prompt(payload)


class WhatItOffers(unittest.TestCase):
    def test_the_options_plus_an_escape_hatch(self):
        self.assertEqual(_picker().options, ("yes", "no", SOMETHING_ELSE))

    def test_something_else_is_always_last(self):
        picker = _picker(options=["approve", "deny", "ask me later"])
        self.assertEqual(picker.options[-1], SOMETHING_ELSE)

    def test_a_prompt_with_no_options_still_asks_something(self):
        """Guardian has sent a prompt with an empty options list; a
        picker with no bullets is a dead end."""
        self.assertEqual(_picker(options=[]).options, ("yes", "no", SOMETHING_ELSE))

    def test_the_question_is_the_heading(self):
        self.assertIn("Backyard Door", _picker().heading)


class NothingIsPreselected(unittest.TestCase):
    """The whole reason this exists is that typing "yes" at the old
    prompt was too easy to get wrong."""

    def test_no_bullet_is_marked_when_it_opens(self):
        picker = _picker()
        self.assertIsNone(picker.chosen)
        self.assertEqual([m for _t, _c, m in picker.lines()], [False, False, False])

    def test_the_cursor_starts_on_the_first_option_but_marks_nothing(self):
        picker = _picker()
        self.assertEqual([c for _t, c, _m in picker.lines()], [True, False, False])


class MovingAndMarking(unittest.TestCase):
    def test_space_marks_and_marks_again_to_unmark(self):
        picker = _picker()
        picker.space()
        self.assertEqual(picker.chosen, "yes")
        picker.space()
        self.assertIsNone(picker.chosen, "marking twice is a change of mind")

    def test_marking_a_second_option_replaces_the_first(self):
        """One approval, one answer."""
        picker = _picker()
        picker.space()
        picker.move(1)
        picker.space()
        self.assertEqual(picker.chosen, "no")

    def test_the_ends_do_not_wrap(self):
        """Pressing down once too often on "no" must not arrive back
        at "yes"."""
        picker = _picker()
        for _ in range(10):
            picker.move(1)
        self.assertEqual(picker.rows[picker.cursor], SOMETHING_ELSE)
        for _ in range(10):
            picker.move(-1)
        self.assertEqual(picker.rows[picker.cursor], "yes")


class TheConfirmStep(unittest.TestCase):
    def test_enter_goes_to_confirm_and_names_the_answer(self):
        picker = _picker()
        picker.move(1)
        picker.space()
        self.assertEqual(picker.enter(), CONFIRMING)
        self.assertIn("'no'", picker.heading)
        self.assertEqual(picker.rows, (SUBMIT, REDO))

    def test_the_confirm_step_names_the_answer_not_the_position(self):
        """"Submit option 2?" is not something anybody can check."""
        picker = _picker()
        picker.space()
        picker.enter()
        self.assertIn("yes", picker.heading)
        self.assertNotIn("1", picker.heading)

    def test_submit_finishes_with_that_answer(self):
        picker = _picker()
        picker.move(1)
        picker.space()
        picker.enter()
        self.assertEqual(picker.enter(), DONE)
        self.assertTrue(picker.done)
        self.assertEqual(picker.answer, "no")

    def test_go_back_returns_to_the_options_with_nothing_marked(self):
        picker = _picker()
        picker.space()
        picker.enter()
        picker.move(1)          # onto "go back"
        self.assertEqual(picker.enter(), CHOOSING)
        self.assertIsNone(picker.chosen, "changing your mind unmarks the old answer")
        self.assertFalse(picker.done)

    def test_enter_on_an_untouched_picker_takes_the_line_under_the_cursor(self):
        """Moving to a line and pressing Enter is what everybody does.
        It is still a keypress on a specific line, which a preselected
        default is not."""
        picker = _picker()
        picker.move(1)
        picker.enter()
        self.assertIn("'no'", picker.heading)


class SomethingElse(unittest.TestCase):
    def test_choosing_it_asks_for_typing(self):
        picker = _picker()
        picker.move(2)
        self.assertEqual(picker.enter(), TYPING)

    def test_what_is_typed_becomes_the_answer_after_a_confirm(self):
        picker = _picker()
        picker.move(2)
        picker.enter()
        self.assertEqual(picker.typed("only the hallway one"), CONFIRMING)
        self.assertIn("only the hallway one", picker.heading)
        picker.enter()
        self.assertEqual(picker.answer, "only the hallway one")

    def test_typing_nothing_is_a_change_of_mind(self):
        picker = _picker()
        picker.move(2)
        picker.enter()
        self.assertEqual(picker.typed("   "), CHOOSING)
        self.assertIsNone(picker.chosen)


class BackingOut(unittest.TestCase):
    def test_escape_never_answers(self):
        picker = _picker()
        picker.space()
        picker.enter()
        picker.escape()
        self.assertFalse(picker.done)
        self.assertEqual(picker.answer, "")

    def test_escape_does_not_close_the_picker(self):
        """An approval a stray key can dismiss is one that times out
        to its default with nobody deciding."""
        picker = _picker()
        picker.escape()
        self.assertEqual(picker.stage, CHOOSING)

    def test_keys_after_it_is_done_change_nothing(self):
        picker = _picker()
        picker.space()
        picker.enter()
        picker.enter()
        answer = picker.answer
        picker.move(1)
        picker.space()
        self.assertEqual(picker.answer, answer)
        self.assertTrue(picker.done)


class WhatItLooksLike(unittest.TestCase):
    def test_the_marked_line_and_the_cursor_are_both_visible(self):
        picker = _picker()
        picker.move(1)
        picker.space()
        text = picker.render()
        self.assertIn("❯", text)
        self.assertIn("◉", text)
        self.assertEqual(len(text.splitlines()), 4, "the question and three bullets")

    def test_the_typing_step_has_no_bullets(self):
        picker = _picker()
        picker.move(2)
        picker.enter()
        self.assertEqual(len(picker.render().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()


class TheTuiSideOfIt(unittest.TestCase):
    """The keys only mean this while an approval is up.

    An arrow key is history and the space bar is a space the rest of
    the time, and a picker that captured them permanently would be a
    worse bug than the one it fixes.
    """

    def _tui(self):
        from simorgh.interface.tui import Tui

        async def _line(_text):
            return None

        return Tui(on_line=_line)

    def test_nothing_is_captured_when_no_approval_is_waiting(self):
        self.assertFalse(self._tui().picking())

    def test_an_approval_puts_bullets_above_the_prompt(self):
        tui = self._tui()
        tui.ask({"question": "Approve notify?", "options": ["yes", "no"], "prompt_id": "p1"})
        self.assertTrue(tui.picking())
        text = "".join(fragment for _style, fragment in tui._picker_rows())
        self.assertIn("Approve notify?", text)
        self.assertIn("yes", text)
        self.assertIn(SOMETHING_ELSE, text)

    def test_confirming_calls_back_with_the_answer_and_clears(self):
        tui = self._tui()
        answered = []
        tui._on_answer = lambda prompt_id, answer: answered.append((prompt_id, answer))
        tui.ask({"question": "Approve?", "options": ["yes", "no"], "prompt_id": "p1"})
        tui._picker.move(1)
        tui._picker.space()
        tui._picker.enter()
        tui._picker.enter()
        tui._finish_picker()
        self.assertEqual(answered, [("p1", "no")])
        self.assertFalse(tui.picking(), "the section goes back to being the prompt")

    def test_the_keys_are_released_while_typing_something_else(self):
        """The input line has to take the text, so the picker must not
        be swallowing keys at that moment."""
        tui = self._tui()
        tui.ask({"question": "Approve?", "options": ["yes", "no"], "prompt_id": "p1"})
        tui._picker.move(2)
        tui._picker.enter()
        self.assertFalse(tui.picking())

    def test_a_typed_answer_is_not_run_as_a_command(self):
        """`home off kitchen` typed at that moment must not turn the
        light off and leave the approval hanging."""
        tui = self._tui()
        tui.ask({"question": "Approve?", "options": ["yes", "no"], "prompt_id": "p1"})
        tui._picker.move(2)
        tui._picker.enter()
        self.assertTrue(tui._typing_an_answer("home off kitchen"))
        self.assertIn("home off kitchen", tui._picker.heading)

    def test_an_ordinary_line_is_left_alone(self):
        tui = self._tui()
        self.assertFalse(tui._typing_an_answer("tasks"))
