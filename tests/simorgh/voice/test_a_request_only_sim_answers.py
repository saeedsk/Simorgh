"""A request only Sim answers is for Sim, even unnamed.

The creator, 2026-09-20: his daughter Ira sang in the kitchen, and a
moment later he said out loud "tell me a story from the Arabian Nights
book". Nothing happened. Typed into the prompt, the same words worked
and the story came back on screen.

`_bystander` was the rule that swallowed it. It sits out anything that
is neither a question nor names Sim when another known voice has
spoken in the last little while -- which describes a plain imperative
request exactly, and Ira had just sung.

The fix is deliberately not "answer every imperative". Widening "is
this for me" is how this project has hurt itself twice: "Can you try a
bit harder next time, honey." came back as Sim apologising. So the
test the code applies is narrower -- does this ask for something only
SIM does? A parent says "set a timer" and "turn the light off" to the
house, never to a five-year-old, and the vocative rule still outranks
it so "read Aran a story" stays a parent organising an evening.
"""

import unittest

from simorgh.voice.backchannel import asks_for_something_sim_does

NAMES = ("Ira", "Iris", "Aran", "Soodeh")


class ARequestOnlySimAnswers(unittest.TestCase):
    def _asks(self, text: str) -> bool:
        return asks_for_something_sim_does(text, names=NAMES)

    def test_the_story_the_creator_asked_for_out_loud(self) -> None:
        self.assertTrue(self._asks("Tell me a story from the Arabian Nights book."))

    def test_the_things_a_house_does_and_a_child_does_not(self) -> None:
        for text in (
            "Set a timer for ten minutes",
            "Remind me at six",
            "Turn the kitchen light on",
            "switch off the lamp",
            "play some music",
            "read me the news",
            "what's on my calendar",
        ):
            self.assertTrue(self._asks(text), text)

    def test_the_asides_that_must_stay_asides(self) -> None:
        """Every one of these is a sentence Sim has wrongly answered
        before, or would have under a looser rule."""
        for text in (
            "Can you try a bit harder next time, honey.",
            "I said we are leaving in five minutes.",
            "Did you move the blue folder?",
            "Don't be a dumb-dumb",
            "I told you to put your shoes on",
        ):
            self.assertFalse(self._asks(text), text)

    def test_naming_somebody_else_wins(self) -> None:
        """A parent handing the bedtime story to the other parent is
        not asking the house for one."""
        self.assertFalse(self._asks("read Aran a story"))
        self.assertFalse(self._asks("Soodeh, play some music"))

    def test_nothing_is_not_a_request(self) -> None:
        self.assertFalse(self._asks(""))
        self.assertFalse(self._asks("   "))


if __name__ == "__main__":
    unittest.main()
