"""The five cartoon splash screens: exactly five, all printable, and
`splash_art.pick()` always returns one of them."""
import unittest

from simorgh.interface import splash_art


class TestCartoonSplash(unittest.TestCase):
    def test_there_are_five_cartoons(self):
        self.assertEqual(len(splash_art.CARTOON_SPLASHES), 5)

    def test_pick_returns_one_of_them(self):
        name, art = splash_art.pick()
        self.assertIn((name, art), splash_art.CARTOON_SPLASHES)

    def test_every_line_is_printable_and_fits_the_rule(self):
        for _, art in splash_art.CARTOON_SPLASHES:
            self.assertTrue(art, "a cartoon with no lines")
            for line in art:
                self.assertTrue(line.strip(), f"blank line in {line!r}")
                self.assertLessEqual(len(line), 80, line)


if __name__ == "__main__":
    unittest.main()
