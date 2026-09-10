"""The five things that stood between Sim and editing its own source.

Traced 2026-09-07 by running one task under control and watching every
turn. Sim had executed 246 tools across its whole life and never once
written a file. Each of these was enough on its own to stop it, and they
had to be removed in order before the first real commit appeared.

Once all five were fixed, asked to create a file, Sim wrote it, ran the
tests, and committed it -- `d832579 Add greeting.greet(name) returning
'hello, <name>'`, author Simorgh.
"""

from __future__ import annotations

import unittest

from simorgh.cognition.parser import OutputParser, parse_marker
from simorgh.orchestration import profiles, scaffolds
from simorgh.orchestration.session import SessionRunner

_TOOLS = tuple(profiles.PATCH.tools)


class TestTheModelIsShownWhatItsToolsReturned(unittest.TestCase):
    """1. The tool result handed back to the model was cut to 200
    characters. It read a 5,457-character file, saw the first 200, and
    read it again -- eight times, replying only "READ_FILE: ..." each
    time. It cannot patch a file it has never been allowed to see."""

    def test_a_whole_source_file_survives_the_bound(self):
        self.assertGreaterEqual(SessionRunner._MODEL_RESULT_CHARS, 8000)  # noqa: SLF001

    def test_the_model_sees_far_more_than_the_narration_keeps(self):
        """The narration bound is for a log line; this one is the model's
        only window onto the repo. Conflating them was the bug."""
        self.assertGreater(SessionRunner._MODEL_RESULT_CHARS, SessionRunner._DETAIL_CHARS)  # noqa: SLF001


class TestAMarkerAfterAPreambleIsStillACall(unittest.TestCase):
    """2. `parse_marker` only accepted a marker at the very start of the
    reply. The model writes a sentence first, so the call was invisible
    and the reply was filed as a final answer."""

    def test_a_call_after_one_line_of_preamble(self):
        text = "Let me get my bearings before continuing.\nSEARCH_CODE: persona"
        self.assertEqual(parse_marker(text, _TOOLS), ("search_code", "persona"))

    def test_the_documented_form_still_wins(self):
        self.assertEqual(parse_marker("READ_FILE: a.py", _TOOLS), ("read_file", "a.py"))

    def test_a_marker_named_inside_a_sentence_stays_prose(self):
        text = "The tool READ_FILE: is how you read a file."
        self.assertEqual(parse_marker(text, _TOOLS)[0], None)

    def test_a_real_reply_that_reasoned_before_committing(self):
        """Verbatim from the run that produced Sim's first commit."""
        text = (
            "RUN_TESTS found nothing to run -- there's no test for the new file yet.\n"
            "The change is applied; next step is to commit it.\n\n"
            "GIT_COMMIT: simorgh/greeting.py\nAdd greeting.greet(name)"
        )
        marker, payload = parse_marker(text, _TOOLS)
        self.assertEqual(marker, "git_commit")
        self.assertTrue(payload.startswith("simorgh/greeting.py"))


class TestACommitKeepsItsMessage(unittest.TestCase):
    """3. `git_commit` takes two fields -- first line the path, the rest
    the message -- but only "code-bearing" markers kept a multi-line
    payload. So the message was cut off and the commit went out empty.
    Watched live: Sim wrote its first real file and then failed to commit
    it three times, every attempt `args={'message': '', ...}`."""

    def test_the_message_after_the_path_is_not_discarded(self):
        parsed = OutputParser().parse(
            "GIT_COMMIT: simorgh/greeting.py\nAdd greet(name)",
            {"kind": "markers", "markers": _TOOLS},
        )
        self.assertEqual(parsed.kind, "tool_calls")
        argument = parsed.tool_calls[0]["args"]["argument"]
        self.assertIn("simorgh/greeting.py", argument)
        self.assertIn("Add greet(name)", argument)

    def test_a_single_token_tool_still_takes_only_its_first_line(self):
        parsed = OutputParser().parse(
            "READ_FILE: a.py\nand some chatter after it",
            {"kind": "markers", "markers": _TOOLS},
        )
        self.assertEqual(parsed.tool_calls[0]["args"]["argument"], "a.py")


class TestTheTaskCannotBeCompactedAway(unittest.TestCase):
    """4. The task lived in the elastic conversation, so a large tool
    result pushed it out. The moment the model was finally shown a whole
    file, its next reply was "I have the full file in hand, but the
    change itself was never specified"."""

    def test_the_task_is_in_the_protected_rules_block(self):
        rules = scaffolds.render(profiles.PATCH, task="add a docstring to vitals.py")
        self.assertIn("add a docstring to vitals.py", rules)

    def test_a_known_subject_is_named_so_it_need_not_search_for_it(self):
        """5. Handed a task naming the exact file, it spent every step
        searching -- including the retired v1 tree -- and then had to
        answer having applied nothing."""
        rules = scaffolds.render(profiles.PATCH, subject="simorgh/x.py", task="do a thing")
        self.assertIn("simorgh/x.py", rules)
        self.assertIn("do not go looking for it", rules)

    def test_a_task_with_no_subject_still_renders(self):
        rules = scaffolds.render(profiles.PATCH, task="something broad")
        self.assertIn("something broad", rules)


class TestRoomToFinish(unittest.TestCase):
    """A patch is read, apply, test, commit -- four tool calls before a
    single wrong turn, and the last step is spent on the forced final
    answer."""

    def test_a_patch_session_has_steps_left_after_the_four_it_needs(self):
        self.assertGreaterEqual(profiles.PATCH.max_steps, 10)

    def test_a_patch_session_can_emit_a_whole_file(self):
        """`apply_source_patch` takes the complete new content, and the
        budget is shared with a reasoning model's thinking tokens."""
        self.assertGreaterEqual(profiles.PATCH.max_output_tokens, 8000)
        self.assertGreaterEqual(profiles.SKILL.max_output_tokens, 8000)

    def test_a_chat_turn_can_also_emit_a_whole_file(self):
        """This test used to assert the opposite, and the premise it
        rested on is gone.

        A chat turn could only talk, so a reply-sized output budget was
        right. It can now write files, install packages and run scripts
        -- and with a 2,000-token budget every `apply_source_patch` on
        anything long truncated part-way, so the file came out shorter
        than it went in. Live-caught 2026-09-09: 147 lines became 131,
        then 129, then 76, then 54.

        What separates chat from patch is the scaffold and whether the
        work is verified, not how much room it has to write.
        """
        self.assertGreaterEqual(profiles.CHAT.max_output_tokens, 8000)

    def test_a_chat_turn_that_can_write_has_room_to_finish(self):
        """Write, install what it needs, run it, check it -- before a
        single wrong turn, and with the last step spent on the forced
        final answer."""
        self.assertGreaterEqual(profiles.CHAT.max_steps, 15)


if __name__ == "__main__":
    unittest.main()
