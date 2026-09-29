"""A marker's payload ends where the model starts writing our side.

Bench wave, 2026-09-29: the model wrote `RUN_SHELL: pwd; find / ...` and
then, in the same reply, "[user] Result of run_shell:\\n/\\nfind:
'/proc/1/map_files': Permission denied ..." -- an invented Linux answer.
All of it ran as one shell command, and the model believed its own "/"."""

from __future__ import annotations

import unittest

from simorgh.cognition.parser import parse_marker


class ACallStopsWhereTheReplyIsInvented(unittest.TestCase):
    def test_an_invented_result_is_not_part_of_the_command(self):
        text = ("RUN_SHELL: pwd; find / -name \"df6561b2*\" 2>/dev/null | head\n\n"
                "[user] Right now it is Tuesday 29 September 2026, 08:23.\n\n"
                "Result of run_shell:\n/\nfind: '/proc/1/map_files': Permission denied")
        self.assertEqual(parse_marker(text, ("RUN_SHELL",)),
                         ("run_shell", 'pwd; find / -name "df6561b2*" 2>/dev/null | head'))

    def test_after_a_line_of_preamble_too(self):
        text = "Let me look.\nRUN_SHELL: ls\n[assistant] RUN_SHELL: ls -la"
        self.assertEqual(parse_marker(text, ("RUN_SHELL",)), ("run_shell", "ls"))

    def test_a_bare_result_header_cuts_it(self):
        text = "RUN_SHELL: ls workspace\nResult of run_shell:\nscratch"
        self.assertEqual(parse_marker(text, ("RUN_SHELL",))[1], "ls workspace")

    def test_a_multi_line_patch_is_left_whole(self):
        body = 'a.py\nx = "[user] said Result of run_shell: nothing"\n[user]: https://example.com\nprint(1)'
        self.assertEqual(parse_marker("APPLY_SOURCE_PATCH: " + body, ("APPLY_SOURCE_PATCH",))[1], body)


if __name__ == "__main__":
    unittest.main()
