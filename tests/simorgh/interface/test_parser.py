import unittest

from simorgh.interface.parser import parse


class ParserTestCase(unittest.TestCase):
    def test_plain_text_is_chat(self):
        cmd = parse("how are you doing today")
        self.assertIsNone(cmd.name)
        self.assertEqual(cmd.args, "how are you doing today")

    def test_recognized_command_with_args(self):
        cmd = parse("research quantum computing")
        self.assertEqual(cmd.name, "research")
        self.assertEqual(cmd.args, "quantum computing")

    def test_leading_slash_is_optional(self):
        cmd = parse("/status")
        self.assertEqual(cmd.name, "status")

    def test_autocorrect_announces_the_guess(self):
        cmd = parse("porpose a unit converter")
        self.assertEqual(cmd.name, "propose")
        self.assertEqual(cmd.guessed_from, "porpose")
        self.assertEqual(cmd.args, "a unit converter")

    def test_bang_is_shell_passthrough(self):
        cmd = parse("!echo hi")
        self.assertEqual(cmd.name, "!")
        self.assertEqual(cmd.args, "echo hi")

    def test_blank_line_is_none(self):
        self.assertIsNone(parse("   "))

    def test_unrecognized_short_word_is_chat_not_a_guess(self):
        cmd = parse("hey there")
        self.assertIsNone(cmd.name)
        self.assertIsNone(cmd.guessed_from)


if __name__ == "__main__":
    unittest.main()
