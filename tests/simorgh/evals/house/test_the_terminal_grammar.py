"""Stage 11 item 9: what may and may not reach the terminal.

Not a style check. Every rule is something that actually reached the
creator's screen and either told him nothing or told him something
untrue. The `? · ? · (no description)` rule is the one that earned the
rest: it turned out every message he had ever sent Sim from Telegram
rendered that way, because the interface learnt a turn's description
from the console or from `voice.transcript` and a phone has neither.
"""

import unittest

from simorgh.evals.house.record import Record
from simorgh.evals.house.script import tui_is_sane


def _printed(*lines) -> tuple[Record, float]:
    import time

    record, since = Record(), time.monotonic()
    for line in lines:
        record.printed_line(line)
    return record, since


class WhatMustNeverShow(unittest.TestCase):
    def test_a_stack_trace(self):
        record, since = _printed("Traceback (most recent call last):")
        self.assertIn("stack trace", tui_is_sane().check(record, since))

    def test_a_librarys_progress_bar(self):
        for bar in ("Loading weights: 100%|##| 103/103", "Batches: 100%|###| 1/1 [00:00<00:00, 24it/s]"):
            record, since = _printed(bar)
            self.assertNotEqual(tui_is_sane().check(record, since), "", bar)

    def test_a_task_nobody_named(self):
        """The Telegram bug: `⏺ • ? · ? · (no description)`."""
        record, since = _printed("⏺ • ? · ? · (no description)  [4cdfa8c4]")
        self.assertIn("nobody named", tui_is_sane().check(record, since))

    def test_a_raw_payload(self):
        record, since = _printed("action.result {'ok': False, 'error': 'nope'}")
        self.assertIn("raw payload", tui_is_sane().check(record, since))

    def test_an_empty_answer_line(self):
        record, since = _printed("🔊 sim:")
        self.assertIn("empty line", tui_is_sane().check(record, since))

    def test_a_line_wider_than_a_terminal(self):
        record, since = _printed("x" * 300)
        self.assertIn("characters wide", tui_is_sane().check(record, since))

    def test_the_same_line_twice_in_a_row(self):
        record, since = _printed("  🎤 listening...", "  🎤 listening...")
        self.assertIn("same line twice", tui_is_sane().check(record, since))

    def test_colour_does_not_hide_a_breach(self):
        """Every line on the real terminal carries escape codes; a
        grammar that only reads plain text checks nothing."""
        record, since = _printed("\x1b[2m⏺ • ? · ? · (no description)\x1b[0m")
        self.assertNotEqual(tui_is_sane().check(record, since), "")


class WhatIsFine(unittest.TestCase):
    def test_an_ordinary_exchange_passes(self):
        record, since = _printed(
            "  🎤 listening...",
            "⏺ 💬 chat · telegram · what is the weather  [0c458741]",
            "  ⎿  ✅ completed in 0.4s -- Bright and cold.",
            "🔊 sim: Bright and cold.",
            "  🤫 not for me -- staying quiet",
        )
        self.assertEqual(tui_is_sane().check(record, since), "")

    def test_nothing_printed_is_not_a_breach(self):
        record, since = _printed()
        self.assertEqual(tui_is_sane().check(record, since), "")

    def test_the_same_line_twice_apart_is_fine(self):
        """A prompt repeating through a session is normal; twice in a
        row is a bug."""
        record, since = _printed("  🎤 listening...", "🔊 sim: yes", "  🎤 listening...")
        self.assertEqual(tui_is_sane().check(record, since), "")


class ATelegramTurnIsNamed(unittest.IsolatedAsyncioTestCase):
    """The fix, from the outside: a turn from a channel that narrates
    nothing still reads as something a person recognises."""

    async def test_the_percept_names_the_task_when_nobody_else_does(self):
        import uuid

        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message
        from simorgh.evals.house import Director, Sandbox

        async with Sandbox() as box:
            director = Director(box)
            mark = director.now()
            await box.kernel.bus.publish(Message.new(
                topics.PERCEPT_TEXT_RECEIVED, source="interface",
                payload={"channel": "telegram", "text": "what is the weather",
                         "session_id": uuid.uuid4().hex, "speaker": "Mara"}))
            await director.settle(since=mark, quiet_for=1.0)
            self.assertEqual(tui_is_sane().check(director.record, mark), "")
            shown = " ".join(p.text for p in director.record.printed_since(mark))
            self.assertIn("telegram", shown)
            self.assertIn("what is the weather", shown)


if __name__ == "__main__":
    unittest.main()


class OnePrintCanCarrySeveralLines(unittest.TestCase):
    """The grammar reads physical lines, not prints.

    A task tree's end wraps Sim's answer under its status line, so
    one `printed_line` carries three. Measured as a single string it
    reported "a line 285 characters wide" -- which was three short
    lines with newlines between them. Caught by this expectation
    itself, against the paid provider, an hour after the wrapping
    landed (2026-09-20).

    A checker that cannot read what it is checking invents failures,
    and an invented failure costs more trust than the bug it was
    guarding against.
    """

    def _record(self, *prints):
        from simorgh.evals.house.record import Record

        record = Record()
        for text in prints:
            record.printed_line(text)
        return record

    def test_a_wrapped_block_is_read_line_by_line(self):
        from simorgh.evals.house.script import tui_is_sane

        block = "  ⎿  ✅ completed in 2.5s\n       " + "Good evening, Mara. " * 6
        self.assertEqual(tui_is_sane().check(self._record(block), 0.0), "")

    def test_a_genuinely_wide_line_is_still_caught(self):
        from simorgh.evals.house.script import tui_is_sane

        why = tui_is_sane().check(self._record("x" * 260), 0.0)
        self.assertIn("260 characters wide", why)

    def test_a_wide_line_inside_a_block_is_caught(self):
        """The point of splitting is to see INTO the block, not to
        stop looking."""
        from simorgh.evals.house.script import tui_is_sane

        why = tui_is_sane().check(self._record("  ⎿  ✅ completed\n       " + "y" * 260), 0.0)
        self.assertIn("characters wide", why)

    def test_a_stack_trace_inside_a_block_is_caught(self):
        from simorgh.evals.house.script import tui_is_sane

        why = tui_is_sane().check(
            self._record("  ⎿  ✅ completed\n       Traceback (most recent call last):"), 0.0)
        self.assertIn("stack trace", why)
